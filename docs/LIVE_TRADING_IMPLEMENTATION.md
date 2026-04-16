# Strategy and live implementation — source of truth

This document is the **authoritative** description of the trading strategy logic, backtest assumptions, and how to implement the same behavior in production. It is written for engineers building execution and risk systems. All configuration names below are the canonical parameter names to use in any implementation.

---

## Part A — Strategy and backtest specification

### A.1 Strategy intent

The strategy trades a **four-leg option structure** on an index underlying (for example SENSEX via `BSE_INDEX|SENSEX`): simultaneous **short call spread** and **short put spread** (iron-condor-style: short CE, long CE, short PE, long PE). Optional **multi-phase** rules roll or exit legs when short premiums or portfolio PnL cross thresholds.

Everything below uses **1-minute intervals** and **close price** unless stated otherwise. Timezone for candles is **IST (Asia/Kolkata)** after normalization.

---

### A.2 Configuration parameters (canonical list)

**Timing and universe**

| Parameter | Meaning |
|-----------|---------|
| `entry_datetime` | When the position logic starts (first bar used is the first 1m bar at or after this timestamp). |
| `expiry_date` | Option expiry calendar date (`YYYY-MM-DD`). |
| `exit_datetime` | Optional; if omitted, session end defaults to `{expiry_date} 15:30:00`. |
| `underlying_key` | Broker instrument key for the index (e.g. `BSE_INDEX|SENSEX`). |
| `strike_gap` | Strike spacing for the underlying (e.g. 100 for SENSEX). |

**Entry strike selection**

| Parameter | Meaning |
|-----------|---------|
| `target_premium` | Desired premium (close) of each **short** option (CE and PE) at entry. |
| `tolerance` | Accept short strike if `abs(premium - target_premium) <= tolerance`; else pick globally closest premium. |

**Structure**

| Parameter | Meaning |
|-----------|---------|
| `hedge_difference` | Spread width (required). **Call spread:** long call strike = short strike + `hedge_difference`. **Put spread:** long put strike = short strike − `hedge_difference`. |

**Multi-phase engine**

Active when `hedge_difference` is set, four legs are built, and `phase2_trigger_premium` is not null. Tier list is built from optional triggers:

| Parameter | Meaning |
|-----------|---------|
| `phase2_trigger_premium` / `phase2_target_reentry` | First tier: trigger premium and target premium for re-entry on the **opposite** spread. |
| `phase2b_trigger_premium` / `phase2b_target_reentry` | Second tier (optional). |
| `phase2c_trigger_premium` / `phase2c_target_reentry` | Third tier (optional). |
| `phase3_trigger_premium` / `phase3_target_reentry` | Fourth tier (optional). |
| `phase2_strike_range` | Integer `N`: candidate short strikes for re-entry lie in `[ATM − N·strike_gap, ATM + N·strike_gap]`. |
| `phase4_trigger_premium` | If set: when a short leg premium **exceeds** this, that **pair** is closed with no further re-entry on that side (terminal exit for that side). |
| `phase4_target_reentry` | Defined in configuration for symmetry; Phase 4 path **does not** re-enter (square-off only). |

**Risk**

| Parameter | Meaning |
|-----------|---------|
| `stoploss_amount` | If set: when **total** PnL (realized + unrealized) ≤ **−**`stoploss_amount`, square off **both** pairs. |
| `margin` | Used with `profit_pct` for profit-taking trigger. |
| `profit_pct` | If both `margin` and `profit_pct` set: `profit_trigger_amount = margin × (profit_pct / 100)`. |

**Sizing**

| Parameter | Meaning |
|-----------|---------|
| `lot_size` | If set, overrides per-leg lot size from contract metadata for all legs. |

---

### A.3 Market data assumptions (backtest)

- **Options:** Historical **expired** contracts only: 1-minute candles from the broker’s expired-instruments historical API. Candle fields include timestamp, OHLC; strategy uses **close**.
- **Underlying at entry:** 1-minute candles for the underlying on the entry day; LTP for strike selection = **close of first bar with timestamp ≥ `entry_datetime`**.
- **Underlying through session (phase engine):** 1-minute close series from entry through `exit_datetime` for ATM calculation on rolls.
- **Contract lists:** Strikes and `instrument_key` for a given `underlying_key` and `expiry_date` from expired option contract API.

**Live:** Replace expired-contract and expired-candle endpoints with **current** chain, **live or delayed quotes**, and **active** expiries. Logic in Part A stays the same; only data sources change.

---

### A.4 Initial entry: CE and PE short strikes

The same strike-selection procedure runs **twice**: once for calls (`CE`), once for puts (`PE`), using the same `target_premium` and `tolerance`.

**Per option class** (`CE` or `PE`), given `entry_datetime`, `target_premium`, `expiry_date`, `underlying_key`, `strike_gap`, `tolerance`:

1. Convert `entry_datetime` to a timestamp. Obtain **underlying LTP** as the **close** of the first 1m candle whose time is **≥** entry time on the entry session date.
2. Load all option contracts for that underlying and expiry; filter to `instrument_type` matching `CE` or `PE` as appropriate.
3. Sort distinct strikes by **increasing distance** from underlying LTP (numeric distance, not label).
4. For each strike in that order: fetch 1m candles for that strike on the entry date; compute **premium** = close of first candle with time **≥** `entry_datetime`. Skip strikes with no data.
5. If `abs(premium - target_premium) ≤ tolerance`, **select** that strike immediately (first acceptable in distance order).
6. If none qualify, select the strike with **smallest** `abs(premium - target_premium)` among those tried.
7. Record short strike, lot size from contract metadata, and premium at entry.

**Hedge resolution:** For CE, hedge strike = short strike + `hedge_difference`. For PE, hedge strike = short strike − `hedge_difference`. Both hedges must exist in the contract list; otherwise the run cannot proceed.

**Legs:** Short CE, long CE (hedge), short PE, long PE — four instruments total.

---

### A.5 Static four-leg path (no multi-phase engine)

If `phase2_trigger_premium` is null (or the multi-phase preconditions are not met), the position is **held static** from entry through `exit_datetime`: load 1m candles for each of the four legs from entry date through expiry date, clip to `[entry_datetime, exit_datetime]`, and align on a **union** of timestamps (outer join).

**Per leg,** entry reference price = close at `entry_datetime`, or the first bar with time **≥** `entry_datetime` if that timestamp is absent.

**Unrealized PnL per bar per leg:**

- **SELL:** `(entry_close − current_close) × lot_size`
- **BUY:** `(current_close − entry_close) × lot_size`

Missing leg PnL for a timestamp is **0**. Sum the four leg PnLs → `total_pnl` per row. No intra-week rolling or square-off rules apply in this path.

---

### A.6 Multi-phase engine (four-leg state machine)

**Purpose:** After initial four-leg entry, simulate **dynamic** management: terminal exits, stop-loss, and **tiered** rolls driven by **opposing** short premium vs thresholds (or by portfolio profit).

**Prefetch (backtest optimization):** For CE and separately for PE, load 1m closes for every short strike in `[ATM₀ ± phase2_strike_range × strike_gap]` where ATM₀ is from underlying LTP **at entry**, and only strikes where the corresponding hedge strike exists. Also load underlying LTP series from entry through exit for ATM at roll time.

**Timeline:** Union of timestamps from initial CE and initial PE candle indices, clipped to `[entry_datetime, expiry_datetime]`. Forward-fill each strike’s close series onto this timeline. Forward-fill underlying LTP on the same timeline.

**Phase tier list `phase_config`:** Ordered list of `(trigger_premium, target_reentry_premium)` built from configuration:

- Always include `(phase2_trigger_premium, phase2_target_reentry)`.
- Append `(phase2b_trigger_premium, phase2b_target_reentry)` if phase2b trigger is set.
- Append `(phase2c_trigger_premium, phase2c_target_reentry)` if phase2c trigger is set.
- Append `(phase3_trigger_premium, phase3_target_reentry)` if phase3 trigger is set.

**Profit trigger:** If `margin` and `profit_pct` are both set and `margin > 0`, then  
`profit_trigger_amount = margin × (profit_pct / 100)`. Otherwise profit-based trigger is disabled.

**State variables:**

- Current short strikes: `ce_short_strike`, `pe_short_strike`.
- Entry premiums: `entry_ce_short`, `entry_ce_hedge`, `entry_pe_short`, `entry_pe_hedge` (updated on each re-entry).
- `cumulative_realized`.
- `put_pair_phase` and `call_pair_phase` (integer phase counters; advance with rolls).
- `put_pair_squared_off`, `call_pair_squared_off` (booleans; terminal off for that side).
- Lot sizes per current strike (from prefetch maps or override).

**Per-bar evaluation order (must be preserved for identical behavior):**

1. Read closes for current CE and PE short strikes and hedges; if missing, fall back to last known entries as defined in the reference implementation.
2. On first bar where shorts are available, initialize entry premiums if still unset.
3. **Phase 4 (premium terminal exit):** If `phase4_trigger_premium` is set:
   - If short CE close **>** trigger and put side not yet squared and call side not already in terminal state per guard logic: realize call-spread PnL, mark call side squared off, advance call phase marker to terminal.
   - If short PE close **>** trigger and symmetric guards: realize put-spread PnL, mark put side squared off.
   - Guards prevent symmetric double-exit on the same bar when both exceed trigger; one side may exit first.
4. **Stop-loss:** Compute total PnL = `cumulative_realized` + unrealized on **unsquared** legs. If `stoploss_amount` is set and total ≤ **−**`stoploss_amount`, realize and square off **both** pairs (terminal).
5. **Tiered rolls — CE drives put side:** If no leg is in terminal square-off state and call pair phase &lt; 4 and put pair phase ≤ number of tiers:
   - **Premium condition:** short CE close **>** `phase_config[put_pair_phase − 1].trigger` (strict inequality).
   - **Profit condition:** `profit_trigger_amount` is not null and total PnL **≥** `profit_trigger_amount`.
   - If **either** holds: realize current **put** spread at market closes; advance `put_pair_phase`; select **new PE short strike** using **best strike** search with target = `phase_config[put_pair_phase − 1].target_reentry` (see below); reset PE entries to new premiums.
6. **Tiered rolls — PE drives call side:** Symmetric: short PE vs tiers advances **call** side; covers **call** spread; re-enters CE via best strike with call targets.
7. **Mark-to-market:** Compute per-leg and `total_pnl` for the row. Call-spread PnL and put-spread PnL contribute zero when that side is squared off.

**Best strike search at timestamp `t`:** Given underlying LTP at `t`, `strike_gap`, `strike_range`, hedge strikes must exist:

- `atm = round(ltp / strike_gap) × strike_gap`.
- Consider each candidate short strike `s` in `[atm − strike_range×strike_gap, atm + strike_range×strike_gap]`.
- For CE: hedge at `s + hedge_difference`. For PE: hedge at `s − hedge_difference`.
- Among candidates with valid short and hedge **closes** at `t`, choose `s` minimizing `abs(short_close − target_reentry_premium)`.

If no candidate qualifies, re-entry is skipped (implementation may log a warning).

**PnL formulas for an active call spread (short CE + long CE):**  
`(entry_ce_short − close_ce_short) × lot_ce_short + (close_ce_hedge − entry_ce_hedge) × lot_ce_hedge`.  
Put spread symmetric.

---

### A.7 What the backtest does not model

- Bid/ask spread, slippage, brokerage, taxes.
- Partial fills, order rejections, latency.
- Liquidity or open-interest filters.
- “Max drawdown” in a portfolio sense — summary stats may use min/max of cumulative PnL series, which is **not** peak-to-trough drawdown unless you compute that separately.

---

## Part B — Live implementation

### B.1 Design goals

| Goal | Meaning |
|------|---------|
| **Rule parity** | Production decisions match Part A for the same prices and parameters. |
| **Execution reality** | Orders, fills, and broker constraints are explicit; state updates on **confirmed** risk where possible. |
| **Safety** | On ambiguity, avoid adding risk (halt, flatten, or manual intervention). |

---

### B.2 Logical architecture

1. **Configuration service** — Loads the parameters in §A.2; versioned and auditable.
2. **Market data** — Streaming or polling: underlying LTP, option quotes or 1m candles for subscribed `instrument_key`s; must match the **price convention** chosen for parity (§B.3).
3. **Strategy engine** — Owns state from §A.6 when the multi-phase engine is active, or static four-leg MTM from §A.5 otherwise; emits **intents** (open four legs, cover spread X, open new spread, flatten all).
4. **Execution service** — Maps intents to broker orders; handles product type (MIS/NRML), quantity, retries; records client order IDs for idempotency.
5. **Ledger and reconciliation** — Syncs broker positions and fills; compares to internal expected quantities; blocks new rolls until prior intents are flat or reconciled.
6. **Operations** — Structured logs, metrics, alerts, **kill switch** independent of strategy code.

---

### B.3 Price and time convention (mandatory)

Pick one definition of “close” for live and document it:

- **Completed 1-minute candle close** (aligned to IST and session) — closest to Part A.
- **Last trade** at minute boundary — may diverge slightly.
- **Mid quote** — systematic divergence from backtest.

Use NTP; log exchange timestamp vs local clock on each decision.

---

### B.4 Entry in production

1. Select **active** weekly expiry and valid `instrument_key`s from the **current** option chain (not expired-only APIs).
2. Compute underlying LTP at `entry_datetime` as in §A.4.
3. Select CE short and PE short and hedges per §A.4.
4. Place four orders; size = `lots × lot_size` (using override or exchange lot).
5. Initialize engine state from **fills** (recommended) or from signal prices (accept slippage tracking).

---

### B.5 Rolls and re-entries

On each phase transition:

1. Close the spread being covered (buy to close short, sell to close long — or broker-specific equivalent).
2. Update `cumulative_realized` from **actual** fill PnL.
3. Run **best strike** search (§A.6) using current LTP and premiums in band.
4. Open new short and hedge for that side.
5. If no strike found: define policy — retry next minute, widen band, or stop.

---

### B.6 Broker and risk (general)

- Verify margin before short option exposure; handle rejections.
- Choose MIS vs NRML and respect auto square-off rules.
- Near expiry, enforce manual or automated **exit before** auction/delivery risk windows (not modeled in Part A).
- Store credentials in a secret manager; alert on auth failure and stop new orders.

---

### B.7 Reconciliation

| Condition | Response |
|-----------|----------|
| Position quantity ≠ expected | Alert; pause strategy; reconcile or flatten |
| Order rejected after retries | Safe mode |
| Duplicate fill event | Idempotent handling by client order id |
| Wild slippage vs signal | Log; optional abort |

After reconciliation events, **broker positions** are authoritative; internal state is corrected.

---

### B.8 Observability

Log at least: entry, roll (put-driven / call-driven), phase-four exit, stop-loss, kill switch — with timestamps, instruments, intended vs filled prices, phases, `total_pnl`.

Metrics: order latency, reject rate, slippage vs theoretical close, divergence between replayed PnL and live PnL.

---

### B.9 Testing path

1. **Unit tests** — Pure functions: PnL formulas, tier list construction, best-strike selection, one-bar transitions with fixed inputs.
2. **Replay** — Historical 1m series fed bar-by-bar; output must match Part A reference outputs within floating tolerance.
3. **Paper trading** — Live connectivity without capital at risk.
4. **Shadow** — Live quotes, log-only orders; compare to theoretical PnL.

---

### B.10 Production readiness checklist

- [ ] All parameters in §A.2 have defined values and change control.
- [ ] Price convention (§B.3) agreed and tested.
- [ ] IST/session/expiry edge cases tested.
- [ ] Kill switch and reconciliation drills passed.
- [ ] Stop-loss and Phase 4 behaviors tested in paper.
- [ ] Compliance and broker terms reviewed.

---

## Part C — Summary

**Part A** defines a **1-minute, close-based** four-leg iron condor: initial CE and PE strike selection by target premium, optional **static** joined-leg MTM through exit, and an optional **multi-phase engine** with tiered premium and profit triggers, Phase 4 premium exits, portfolio stop-loss, and ATM-bounded re-striking.

**Part B** implements the same **state machine** (or static four-leg path) with live data, real orders, fills-based state updates, and operational safeguards. Part A remains the logical oracle for regression testing when fed identical inputs.
