import requests
import pandas as pd
import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.upstox.com/v2"
ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()


def fetch_candle_data(instrument_key, from_date, to_date, interval="1minute"):
    """
    Fetch historical candles from Upstox
    interval: 1minute, 30minute, day, week, month (Upstox allowed)
    """
    # Use expired-instruments endpoint
    # Extend to_date by 1 day to ensure full day data is captured if API behavior is exclusive or timezone shifted
    import datetime
    if isinstance(to_date, str):
        to_date_obj = datetime.datetime.strptime(to_date, "%Y-%m-%d").date()
    else:
        to_date_obj = to_date
        
    extended_to_date = to_date_obj + datetime.timedelta(days=1)
    
    url = f"{BASE_URL}/expired-instruments/historical-candle/{instrument_key}/{interval}/{extended_to_date}/{from_date}"

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Accept": "application/json"
    }

    response = requests.get(url, headers=headers)
    data = response.json()

    if "data" not in data or "candles" not in data["data"]:
        print(f"Error for {instrument_key}: {response.status_code} - {response.text}")
        raise Exception(f"No candle data for {instrument_key}")

    candles = data["data"]["candles"]

    df = pd.DataFrame(
        candles,
        columns=["timestamp", "open", "high", "low", "close", "volume", "oi"]
    )

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    
    # Convert to IST (Asia/Kolkata)
    if df["timestamp"].dt.tz is None:
        # Assume UTC if naive (Upstox often returns UTC-like strings without offset if not explicit)
        # But usually they have offset. Let's force localize if naive, or convert if aware.
        # Actually, best validation is to inspect one.
        # If naive and looks like 03:45, it is UTC.
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    
    df["timestamp"] = df["timestamp"].dt.tz_convert("Asia/Kolkata")
    
    # Remove timezone info for cleaner Excel export, but now in IST
    df["timestamp"] = df["timestamp"].dt.tz_localize(None)

    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)

    return df


def run_weekly_backtest(
    instruments,   # list of dicts: [{instrument_key, side, lot_size}]
    entry_datetime,
    expiry_datetime,
    square_off_short_below=None,  # when short leg (leg 0) close <= this, square off both legs and re-enter same pair; None to disable
):
    """
    instruments example:
    [
        {"instrument_key": "NSE_FO|12345", "side": "SELL", "lot_size": 10},
        {"instrument_key": "NSE_FO|67890", "side": "BUY", "lot_size": 10},
        ...
    ]
    """

    entry_dt = pd.to_datetime(entry_datetime)
    expiry_dt = pd.to_datetime(expiry_datetime)

    combined_df = None

    for i, leg in enumerate(instruments):
        instrument_key = leg["instrument_key"]
        side = leg["side"]
        lot_size = leg["lot_size"]

        # Fetch candle data
        try:
             df = fetch_candle_data(
                instrument_key,
                from_date=entry_dt.date(),
                to_date=expiry_dt.date(),
                interval="1minute"
            )
        except Exception as e:
            print(f"Failed to fetch data for {instrument_key}: {e}")
            continue

        if df.empty:
            print(f"No data in selected range for {instrument_key}")
            continue

        # Filter between entry and expiry
        df = df.sort_index()

        # Ensure entry candle exists
        if entry_dt not in df.index:
            df = df[df.index >= entry_dt]
            if df.empty:
                continue
            entry_price = df.iloc[0]["close"]
        else:
            entry_price = df.loc[entry_dt, "close"]

        df = df[(df.index >= entry_dt) & (df.index <= expiry_dt)]


        # Calculate PnL per minute
        # Store closing price
        col_close = f"close_{instrument_key}_{i}"
        df[col_close] = df["close"]

        col_name = f"pnl_{instrument_key}_{i}"
        if side.upper() == "SELL":
            df[col_name] = (
                (entry_price - df["close"]) * lot_size
            )
        else:  # BUY
            df[col_name] = (
                (df["close"] - entry_price) * lot_size
            )

        leg_df = df[[col_close, col_name]]

        if combined_df is None:
            combined_df = leg_df
        else:
            combined_df = combined_df.join(leg_df, how="outer")

    if combined_df is None or combined_df.empty:
         print("No data found for any leg.")
         return pd.DataFrame()

    # Fill missing timestamps
    combined_df = combined_df.sort_index()
    pnl_columns = [col for col in combined_df.columns if "pnl_" in col]
    combined_df[pnl_columns] = combined_df[pnl_columns].fillna(0)

    # Total PnL column
    combined_df["total_pnl"] = combined_df[pnl_columns].sum(axis=1)

    # Square-off and re-entry: when short leg close <= threshold, realize PnL and re-enter same pair
    if (
        square_off_short_below is not None
        and len(instruments) == 2
        and instruments[0]["side"].upper() == "SELL"
        and instruments[1]["side"].upper() == "BUY"
    ):
        close_0_col = [c for c in combined_df.columns if c.startswith("close_") and c.endswith("_0")][0]
        close_1_col = [c for c in combined_df.columns if c.startswith("close_") and c.endswith("_1")][0]
        pnl_0_col = [c for c in combined_df.columns if c.startswith("pnl_") and c.endswith("_0")][0]
        pnl_1_col = [c for c in combined_df.columns if c.startswith("pnl_") and c.endswith("_1")][0]
        lot_0 = instruments[0]["lot_size"]
        lot_1 = instruments[1]["lot_size"]

        combined_df["square_off"] = 0
        combined_df["entry_short"] = pd.NA
        combined_df["entry_hedge"] = pd.NA

        entry_short = None
        entry_hedge = None
        cumulative_realized = 0.0

        for idx in combined_df.index:
            short_close = combined_df.loc[idx, close_0_col]
            hedge_close = combined_df.loc[idx, close_1_col]
            if pd.isna(short_close):
                continue
            if entry_short is None:
                entry_short = short_close
                entry_hedge = hedge_close if pd.notna(hedge_close) else 0.0
            square_off_triggered = short_close <= square_off_short_below
            if square_off_triggered:
                combined_df.loc[idx, "square_off"] = 1
                hc = hedge_close if pd.notna(hedge_close) else entry_hedge
                round_pnl = (entry_short - short_close) * lot_0 + (hc - entry_hedge) * lot_1
                cumulative_realized += round_pnl
                entry_short = short_close
                entry_hedge = hc
            hc = hedge_close if pd.notna(hedge_close) else entry_hedge
            pnl_0 = (entry_short - short_close) * lot_0
            pnl_1 = (hc - entry_hedge) * lot_1
            combined_df.loc[idx, pnl_0_col] = pnl_0
            combined_df.loc[idx, pnl_1_col] = pnl_1
            combined_df.loc[idx, "total_pnl"] = cumulative_realized + pnl_0 + pnl_1
            combined_df.loc[idx, "entry_short"] = entry_short
            combined_df.loc[idx, "entry_hedge"] = entry_hedge

    return combined_df


def run_weekly_backtest_phase2(
    entry_datetime,
    expiry_datetime,
    initial_ce_short_strike: float,
    initial_pe_short_strike: float,
    trigger_premium: float,
    target_reentry_premium: float,
    hedge_difference: int,
    ce_short_candles: dict,
    ce_hedge_candles: dict,
    pe_short_candles: dict,
    pe_hedge_candles: dict,
    ce_short_lots: dict,
    ce_hedge_lots: dict,
    pe_short_lots: dict,
    pe_hedge_lots: dict,
    underlying_ltp_series: "pd.Series | None" = None,
    strike_gap: int = 100,
    strike_range: int = 15,
    phase3_trigger_premium: float | None = None,
    phase3_target_reentry: float = 55.0,
    phase4_trigger_premium: float | None = None,
    phase4_target_reentry: float = 60.0,
    stoploss_amount: float | None = None,
):
    """
    Stateful backtest with phase-based re-entry:
      - When short CE close > trigger: cover put pair, realize PnL, use underlying LTP at that
        bar to compute ATM, restrict PE candidates to [ATM - N*gap, ATM + N*gap], pick strike
        with premium closest to target_reentry, re-enter new put pair.
      - When short PE close > trigger: same logic for call pair.
    PE hedge = short_strike - hedge_difference (bull put spread).
    CE hedge = short_strike + hedge_difference (bear call spread).
    Candles keyed by short_strike; value = DataFrame (timestamp index, 'close' column).
    """
    entry_dt = pd.to_datetime(entry_datetime)
    expiry_dt = pd.to_datetime(expiry_datetime)

    # Build common timeline from entry to expiry
    if initial_ce_short_strike not in ce_short_candles or initial_pe_short_strike not in pe_short_candles:
        return pd.DataFrame()
    idx_ce = ce_short_candles[initial_ce_short_strike].index
    idx_pe = pe_short_candles[initial_pe_short_strike].index
    timeline = idx_ce.union(idx_pe).sort_values()
    timeline = timeline[(timeline >= entry_dt) & (timeline <= expiry_dt)]

    # Forward-fill underlying LTP over timeline
    ltp_filled = None
    if underlying_ltp_series is not None and not underlying_ltp_series.empty:
        ltp_filled = underlying_ltp_series.reindex(timeline, method="ffill")

    # Forward-fill each strike's close over timeline for lookups
    def filled_series(candle_dict):
        out = {}
        for strike, df in candle_dict.items():
            ser = df["close"].reindex(timeline, method="ffill")
            out[strike] = ser
        return out

    ce_short_filled = filled_series(ce_short_candles)
    ce_hedge_filled = filled_series(ce_hedge_candles)
    pe_short_filled = filled_series(pe_short_candles)
    pe_hedge_filled = filled_series(pe_hedge_candles)

    # Phase config: list of (trigger, target) for phases 2 and 3 only (Phase 4 is square-off, no re-entry)
    phase_config = [(trigger_premium, target_reentry_premium)]
    if phase3_trigger_premium is not None:
        phase_config.append((phase3_trigger_premium, phase3_target_reentry))

    # State
    ce_short_strike = initial_ce_short_strike
    pe_short_strike = initial_pe_short_strike
    entry_ce_short = None
    entry_ce_hedge = None
    entry_pe_short = None
    entry_pe_hedge = None
    cumulative_realized = 0.0
    put_pair_phase = 1   # 1 = initial; advance when short CE exceeds next phase trigger
    call_pair_phase = 1  # 1 = initial; advance when short PE exceeds next phase trigger
    call_pair_squared_off = False  # Phase 4: when True, call pair is closed and PnL zeroed
    put_pair_squared_off = False  # Phase 4: when True, put pair is closed and PnL zeroed

    rows = []
    reentry_ce = 0
    reentry_pe = 0

    def _get_close(filled_dict, strike, ts):
        """Safe lookup: returns float or None."""
        ser = filled_dict.get(strike)
        if ser is None:
            return None
        val = ser.loc[ts] if ts in ser.index else None
        if val is not None and pd.isna(val):
            return None
        return float(val) if val is not None else None

    def _get_ltp_at(ts):
        """Return underlying LTP at timestamp ts (forward-filled)."""
        if ltp_filled is None:
            return None
        val = ltp_filled.loc[ts] if ts in ltp_filled.index else None
        if val is not None and pd.isna(val):
            return None
        return float(val) if val is not None else None

    def _find_best_strike(filled_short, filled_hedge, lots_short, lots_hedge, ts, target, ltp, opt_type):
        """
        Among pre-fetched strikes, restrict to [ATM - range*gap, ATM + range*gap]
        (using underlying LTP to derive ATM), then pick the strike whose short premium
        is closest to target. Also requires hedge data to exist.
        For PE: hedge_strike = short_strike - hedge_difference.
        For CE: hedge_strike = short_strike + hedge_difference.
        Returns (best_strike, short_premium, hedge_premium) or (None, None, None).
        """
        if ltp is not None and strike_gap > 0:
            atm = round(ltp / strike_gap) * strike_gap
            lo = atm - strike_range * strike_gap
            hi = atm + strike_range * strike_gap
        else:
            lo, hi = -float("inf"), float("inf")

        best_s = None
        best_diff = float("inf")
        best_short_prem = None
        best_hedge_prem = None

        for s in filled_short:
            if not (lo <= s <= hi):
                continue
            # Ensure hedge data exists for this strike
            if s not in filled_hedge:
                continue
            val = _get_close(filled_short, s, ts)
            if val is None:
                continue
            diff = abs(val - target)
            if diff < best_diff:
                best_diff = diff
                best_s = s
                best_short_prem = val
                best_hedge_prem = _get_close(filled_hedge, s, ts)

        return best_s, best_short_prem, best_hedge_prem

    for ts in timeline:
        close_ce_short = _get_close(ce_short_filled, ce_short_strike, ts)
        close_ce_hedge = _get_close(ce_hedge_filled, ce_short_strike, ts)
        close_pe_short = _get_close(pe_short_filled, pe_short_strike, ts)
        close_pe_hedge = _get_close(pe_hedge_filled, pe_short_strike, ts)

        # Fallback to last known entry if None
        if close_ce_short is None:
            close_ce_short = entry_ce_short
        if close_ce_hedge is None:
            close_ce_hedge = entry_ce_hedge
        if close_pe_short is None:
            close_pe_short = entry_pe_short
        if close_pe_hedge is None:
            close_pe_hedge = entry_pe_hedge

        # Set initial entries on first valid bar
        if entry_ce_short is None and close_ce_short is not None:
            entry_ce_short = float(close_ce_short)
            entry_ce_hedge = float(close_ce_hedge) if close_ce_hedge is not None else 0.0
        if entry_pe_short is None and close_pe_short is not None:
            entry_pe_short = float(close_pe_short)
            entry_pe_hedge = float(close_pe_hedge) if close_pe_hedge is not None else 0.0

        lot_ce_short = ce_short_lots.get(ce_short_strike, 0)
        lot_ce_hedge = ce_hedge_lots.get(ce_short_strike, 0)
        lot_pe_short = pe_short_lots.get(pe_short_strike, 0)
        lot_pe_hedge = pe_hedge_lots.get(pe_short_strike, 0)

        # ---- Phase 4: square off call pair when call premium > trigger (no re-entry) ----
        if (
            phase4_trigger_premium is not None
            and not call_pair_squared_off
            and close_ce_short is not None
            and float(close_ce_short) > phase4_trigger_premium
        ):
            c_ce = float(close_ce_short)
            c_ce_h = float(close_ce_hedge) if close_ce_hedge is not None else (entry_ce_hedge or 0.0)
            e_ce = entry_ce_short if entry_ce_short is not None else 0.0
            e_ce_h = entry_ce_hedge if entry_ce_hedge is not None else 0.0
            round_pnl = (e_ce - c_ce) * lot_ce_short + (c_ce_h - e_ce_h) * lot_ce_hedge
            cumulative_realized += round_pnl
            call_pair_squared_off = True
            print(f"[Phase4] {ts} | Square off CALL pair: short_ce_close={c_ce:.2f} (entry={e_ce:.2f}), "
                  f"hedge_ce_close={c_ce_h:.2f} (entry={e_ce_h:.2f}), "
                  f"realized_pnl={round_pnl:.2f}, cumulative={cumulative_realized:.2f}")

        # ---- Phase 4: square off put pair when put premium > trigger (no re-entry) ----
        if (
            phase4_trigger_premium is not None
            and not put_pair_squared_off
            and close_pe_short is not None
            and float(close_pe_short) > phase4_trigger_premium
        ):
            c_pe = float(close_pe_short)
            c_pe_h = float(close_pe_hedge) if close_pe_hedge is not None else (entry_pe_hedge or 0.0)
            e_pe = entry_pe_short if entry_pe_short is not None else 0.0
            e_pe_h = entry_pe_hedge if entry_pe_hedge is not None else 0.0
            round_pnl = (e_pe - c_pe) * lot_pe_short + (c_pe_h - e_pe_h) * lot_pe_hedge
            cumulative_realized += round_pnl
            put_pair_squared_off = True
            print(f"[Phase4] {ts} | Square off PUT pair: short_pe_close={c_pe:.2f} (entry={e_pe:.2f}), "
                  f"hedge_pe_close={c_pe_h:.2f} (entry={e_pe_h:.2f}), "
                  f"realized_pnl={round_pnl:.2f}, cumulative={cumulative_realized:.2f}")

        # ---- Phase-based: short CE exceeds next phase trigger -> cover put pair, re-enter put once ----
        if (
            close_ce_short is not None
            and put_pair_phase <= len(phase_config)
            and float(close_ce_short) > phase_config[put_pair_phase - 1][0]
        ):
            next_phase = put_pair_phase + 1
            phase_label = f"[Phase{next_phase}]"
            reentry_target = phase_config[put_pair_phase - 1][1]
            trigger_val = phase_config[put_pair_phase - 1][0]
            c_pe = float(close_pe_short) if close_pe_short is not None else (entry_pe_short or 0.0)
            c_pe_h = float(close_pe_hedge) if close_pe_hedge is not None else (entry_pe_hedge or 0.0)
            if entry_pe_short is not None:
                round_pnl = (entry_pe_short - c_pe) * lot_pe_short + (c_pe_h - entry_pe_hedge) * lot_pe_hedge
                cumulative_realized += round_pnl
                print(f"{phase_label} {ts} | CE trigger: short_ce_close={close_ce_short:.2f} > {trigger_val}")
                print(f"{phase_label}   Cover PUT pair: short_pe_close={c_pe:.2f} (entry={entry_pe_short:.2f}), "
                      f"hedge_pe_close={c_pe_h:.2f} (entry={entry_pe_hedge:.2f}), "
                      f"realized_pnl={round_pnl:.2f}, cumulative={cumulative_realized:.2f}")

            ltp_now = _get_ltp_at(ts)
            new_pe, new_pe_prem, new_pe_hedge_prem = _find_best_strike(
                pe_short_filled, pe_hedge_filled, pe_short_lots, pe_hedge_lots,
                ts, reentry_target, ltp_now, "PE",
            )
            if new_pe is not None:
                atm_now = round(ltp_now / strike_gap) * strike_gap if ltp_now else "N/A"
                print(f"{phase_label}   Re-entry PE: LTP={ltp_now}, ATM={atm_now}, "
                      f"new_strike={new_pe}, premium={new_pe_prem:.2f}, "
                      f"hedge_strike={new_pe - hedge_difference}, hedge_premium={new_pe_hedge_prem}")
                pe_short_strike = new_pe
                entry_pe_short = new_pe_prem
                entry_pe_hedge = new_pe_hedge_prem if new_pe_hedge_prem is not None else 0.0
                close_pe_short = entry_pe_short
                close_pe_hedge = entry_pe_hedge
                lot_pe_short = pe_short_lots.get(pe_short_strike, lot_pe_short)
                lot_pe_hedge = pe_hedge_lots.get(pe_short_strike, lot_pe_hedge)
                put_pair_phase = next_phase
                reentry_pe += 1
            else:
                print(f"{phase_label}   WARNING: No PE strike found for re-entry at {ts}")

        # ---- Phase-based: short PE exceeds next phase trigger -> cover call pair, re-enter call once ----
        if (
            close_pe_short is not None
            and call_pair_phase <= len(phase_config)
            and float(close_pe_short) > phase_config[call_pair_phase - 1][0]
        ):
            next_phase = call_pair_phase + 1
            phase_label = f"[Phase{next_phase}]"
            reentry_target = phase_config[call_pair_phase - 1][1]
            trigger_val = phase_config[call_pair_phase - 1][0]
            c_ce = float(close_ce_short) if close_ce_short is not None else (entry_ce_short or 0.0)
            c_ce_h = float(close_ce_hedge) if close_ce_hedge is not None else (entry_ce_hedge or 0.0)
            if entry_ce_short is not None:
                round_pnl = (entry_ce_short - c_ce) * lot_ce_short + (c_ce_h - entry_ce_hedge) * lot_ce_hedge
                cumulative_realized += round_pnl
                print(f"{phase_label} {ts} | PE trigger: short_pe_close={close_pe_short:.2f} > {trigger_val}")
                print(f"{phase_label}   Cover CALL pair: short_ce_close={c_ce:.2f} (entry={entry_ce_short:.2f}), "
                      f"hedge_ce_close={c_ce_h:.2f} (entry={entry_ce_hedge:.2f}), "
                      f"realized_pnl={round_pnl:.2f}, cumulative={cumulative_realized:.2f}")

            ltp_now = _get_ltp_at(ts)
            new_ce, new_ce_prem, new_ce_hedge_prem = _find_best_strike(
                ce_short_filled, ce_hedge_filled, ce_short_lots, ce_hedge_lots,
                ts, reentry_target, ltp_now, "CE",
            )
            if new_ce is not None:
                atm_now = round(ltp_now / strike_gap) * strike_gap if ltp_now else "N/A"
                print(f"{phase_label}   Re-entry CE: LTP={ltp_now}, ATM={atm_now}, "
                      f"new_strike={new_ce}, premium={new_ce_prem:.2f}, "
                      f"hedge_strike={new_ce + hedge_difference}, hedge_premium={new_ce_hedge_prem}")
                ce_short_strike = new_ce
                entry_ce_short = new_ce_prem
                entry_ce_hedge = new_ce_hedge_prem if new_ce_hedge_prem is not None else 0.0
                close_ce_short = entry_ce_short
                close_ce_hedge = entry_ce_hedge
                lot_ce_short = ce_short_lots.get(ce_short_strike, lot_ce_short)
                lot_ce_hedge = ce_hedge_lots.get(ce_short_strike, lot_ce_hedge)
                call_pair_phase = next_phase
                reentry_ce += 1
            else:
                print(f"{phase_label}   WARNING: No CE strike found for re-entry at {ts}")

        # ---- Stoploss: if total PnL loss exceeds stoploss_amount, square off all positions ----
        _c_ce = float(close_ce_short) if close_ce_short is not None else (entry_ce_short or 0.0)
        _c_ce_h = float(close_ce_hedge) if close_ce_hedge is not None else (entry_ce_hedge or 0.0)
        _c_pe = float(close_pe_short) if close_pe_short is not None else (entry_pe_short or 0.0)
        _c_pe_h = float(close_pe_hedge) if close_pe_hedge is not None else (entry_pe_hedge or 0.0)
        _e_ce = entry_ce_short if entry_ce_short is not None else 0.0
        _e_ce_h = entry_ce_hedge if entry_ce_hedge is not None else 0.0
        _e_pe = entry_pe_short if entry_pe_short is not None else 0.0
        _e_pe_h = entry_pe_hedge if entry_pe_hedge is not None else 0.0
        _pnl_ce = ((_e_ce - _c_ce) * lot_ce_short + (_c_ce_h - _e_ce_h) * lot_ce_hedge) if not call_pair_squared_off else 0.0
        _pnl_pe = ((_e_pe - _c_pe) * lot_pe_short + (_c_pe_h - _e_pe_h) * lot_pe_hedge) if not put_pair_squared_off else 0.0
        _total_pnl = cumulative_realized + _pnl_ce + _pnl_pe
        if stoploss_amount is not None and _total_pnl <= -stoploss_amount:
            if not call_pair_squared_off:
                round_pnl_ce = (_e_ce - _c_ce) * lot_ce_short + (_c_ce_h - _e_ce_h) * lot_ce_hedge
                cumulative_realized += round_pnl_ce
                call_pair_squared_off = True
                print(f"[Stoploss] {ts} | Square off CALL pair: total_pnl={_total_pnl:.2f} <= -{stoploss_amount}, "
                      f"realized_pnl={round_pnl_ce:.2f}, cumulative={cumulative_realized:.2f}")
            if not put_pair_squared_off:
                round_pnl_pe = (_e_pe - _c_pe) * lot_pe_short + (_c_pe_h - _e_pe_h) * lot_pe_hedge
                cumulative_realized += round_pnl_pe
                put_pair_squared_off = True
                print(f"[Stoploss] {ts} | Square off PUT pair: realized_pnl={round_pnl_pe:.2f}, cumulative={cumulative_realized:.2f}")

        # Current lot sizes (may have changed after re-entry)
        lot_ce_short = ce_short_lots.get(ce_short_strike, 0)
        lot_ce_hedge = ce_hedge_lots.get(ce_short_strike, 0)
        lot_pe_short = pe_short_lots.get(pe_short_strike, 0)
        lot_pe_hedge = pe_hedge_lots.get(pe_short_strike, 0)

        c_ce_s = float(close_ce_short) if close_ce_short is not None else (entry_ce_short or 0.0)
        c_ce_h = float(close_ce_hedge) if close_ce_hedge is not None else (entry_ce_hedge or 0.0)
        c_pe_s = float(close_pe_short) if close_pe_short is not None else (entry_pe_short or 0.0)
        c_pe_h = float(close_pe_hedge) if close_pe_hedge is not None else (entry_pe_hedge or 0.0)
        e_ce_s = entry_ce_short if entry_ce_short is not None else 0.0
        e_ce_h = entry_ce_hedge if entry_ce_hedge is not None else 0.0
        e_pe_s = entry_pe_short if entry_pe_short is not None else 0.0
        e_pe_h = entry_pe_hedge if entry_pe_hedge is not None else 0.0

        pnl_ce_short = (e_ce_s - c_ce_s) * lot_ce_short if not call_pair_squared_off else 0.0
        pnl_ce_hedge = (c_ce_h - e_ce_h) * lot_ce_hedge if not call_pair_squared_off else 0.0
        pnl_pe_short = (e_pe_s - c_pe_s) * lot_pe_short if not put_pair_squared_off else 0.0
        pnl_pe_hedge = (c_pe_h - e_pe_h) * lot_pe_hedge if not put_pair_squared_off else 0.0
        total_pnl = cumulative_realized + pnl_ce_short + pnl_ce_hedge + pnl_pe_short + pnl_pe_hedge

        rows.append({
            "short_ce_close": c_ce_s,
            "hedge_ce_close": c_ce_h,
            "short_pe_close": c_pe_s,
            "hedge_pe_close": c_pe_h,
            "short_ce_strike": ce_short_strike,
            "short_pe_strike": pe_short_strike,
            "hedge_ce": f"{int(ce_short_strike + hedge_difference)} CE",
            "hedge_pe": f"{int(pe_short_strike - hedge_difference)} PE",
            "short_ce_pnl": pnl_ce_short,
            "hedge_ce_pnl": pnl_ce_hedge,
            "short_pe_pnl": pnl_pe_short,
            "hedge_pe_pnl": pnl_pe_hedge,
            "total_pnl": total_pnl,
        })

    print(f"Backtest complete: reentry_ce={reentry_ce}, reentry_pe={reentry_pe}, "
          f"put_pair_phase={put_pair_phase}, call_pair_phase={call_pair_phase}, "
          f"call_pair_squared_off={call_pair_squared_off}, put_pair_squared_off={put_pair_squared_off}, "
          f"final cumulative_realized={cumulative_realized:.2f}")

    result_df = pd.DataFrame(rows, index=timeline)
    result_df.index.name = "timestamp"
    return result_df


if __name__ == "__main__":
    instruments = [
        {"instrument_key": "BSE_FO|1140804|29-07-2025", "side": "SELL", "lot_size": 20},
        {"instrument_key": "BSE_FO|1175477|29-07-2025", "side": "SELL", "lot_size": 20},
        {"instrument_key": "BSE_FO|1140462|29-07-2025", "side": "SELL", "lot_size": 20},
    ]

    result_df = run_weekly_backtest_phase2(
        instruments=instruments,
        entry_datetime="2025-07-25 09:20:00",
        expiry_datetime="2025-07-29 15:30:00"
    )

    result_df.to_excel("backtest_results_fixed.xlsx")
    print("Results saved to backtest_results_fixed.xlsx")
