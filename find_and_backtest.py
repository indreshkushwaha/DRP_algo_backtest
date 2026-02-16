"""
Find Instrument to Short and Run Backtest
=========================================
Given entry date/time and target premium, fetches underlying LTP (1-min candles),
finds the option contract whose premium at entry is nearest to target (with strike
adjustment), and runs the weekly backtest from main.py to produce an Excel result.

Usage:
    Update CONFIGURATION below and run: python find_and_backtest.py
"""

import os
import sys
import urllib.parse
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv

import upstox_api

load_dotenv()

# -----------------------------------------------------------------------------
# CONFIGURATION - update these values
# -----------------------------------------------------------------------------
ENTRY_DATETIME = "2025-07-25 14:50:00"
TARGET_PREMIUM = 50.0
EXPIRY_DATE = "2025-07-29"
UNDERLYING_KEY = "BSE_INDEX|SENSEX"
OPTION_TYPE = "CE"   # "CE" or "PE"
STRIKE_GAP = 100     # e.g. 100 for SENSEX, 50 for Nifty 50
TOLERANCE = 5.0     # accept strike if |premium - target| <= TOLERANCE
HEDGE_DIFFERENCE = 300  # long call/put at short_strike + this (e.g. short 85000 CE, hedge 300 -> long 85300 CE); 0 to disable
SQUARE_OFF_WHEN_SHORT_BELOW = 145.0  # when short leg close <= this, square off both legs and re-enter same pair; None to disable
SHORT_PAIR = True  # True: short CE + hedge CE + short PE + hedge PE at same entry/target; False: single option (OPTION_TYPE)
# Phase 2: when short CE > trigger, cover put pair and re-enter put at premium ~ target_reentry; when short PE > trigger, cover call pair and re-enter call at target_reentry
PHASE2_TRIGGER_PREMIUM = 68.0  # trigger when short leg close > this; None to disable Phase 2
PHASE2_TARGET_REENTRY = 50.0   # target premium when re-entering the other pair
PHASE2_STRIKE_RANGE = 15       # ATM ± this many strike_gap steps for multi-strike pre-fetch
# Phase 3: when short leg > this trigger, re-enter other pair at Phase 3 target (higher tier than Phase 2)
PHASE3_TRIGGER_PREMIUM = 98.0  # trigger when short leg close > this; use Phase 3 re-entry target; None to disable
PHASE3_TARGET_REENTRY = 45.0    # target premium when re-entering under Phase 3
# Phase 4: when short leg > this trigger and side is in Phase 3, re-enter once at Phase 4 target; None to disable
PHASE4_TRIGGER_PREMIUM = 115   # float or None
PHASE4_TARGET_REENTRY = 65.0    # used when Phase 4 trigger is set and exceeded
# Stoploss: when total PnL (realized + unrealized) is loss more than this amount, square off all positions; None to disable
STOPLOSS_AMOUNT = 5000  # e.g. 5000.0
OUTPUT_EXCEL = "backtest_results_fixed.xlsx"



BASE_URL = "https://api.upstox.com/v2"


def _get_access_token():
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token or token == "your_access_token_here":
        print("ERROR: Set UPSTOX_ACCESS_TOKEN in .env")
        sys.exit(1)
    return token


def get_underlying_ltp_at_entry(underlying_key: str, entry_dt: datetime, token: str) -> float:
    """
    Fetch underlying LTP using 1-minute candles. Returns the close of the
    first candle at or after entry_dt (same rule as main.py).
    """
    date_str = entry_dt.strftime("%Y-%m-%d")
    encoded_key = urllib.parse.quote(underlying_key, safe="")
    url = f"{BASE_URL}/historical-candle/{encoded_key}/1minute/{date_str}/{date_str}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    resp = upstox_api.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        print(f"ERROR: Underlying candle API {resp.status_code}: {resp.text[:200]}")
        return 0.0
    data = resp.json()
    candles = data.get("data", {}).get("candles", [])
    if not candles:
        print(f"ERROR: No 1-min candle data for underlying on {date_str}")
        return 0.0

    # Candle format: [timestamp, open, high, low, close, volume, oi] (index 4 = close)
    df = pd.DataFrame(candles)
    df["timestamp"] = pd.to_datetime(df[0])
    df["close"] = pd.to_numeric(df[4], errors="coerce")
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    df = df.sort_values("timestamp")
    df = df[df["timestamp"] >= entry_dt]
    if df.empty:
        print("ERROR: No underlying candle at or after entry time")
        return 0.0
    ltp = float(df.iloc[0]["close"])
    print(f"Underlying LTP at entry ({entry_dt}): {ltp}")
    return ltp


def get_option_premium_at_entry(instrument_key: str, entry_dt: datetime, token: str) -> float | None:
    """
    Fetch 1-minute candles for the option and return close of first candle at or after entry_dt.
    Uses same logic as main.py. Returns None if no data.
    """
    from main import fetch_candle_data

    try:
        df = fetch_candle_data(
            instrument_key,
            from_date=entry_dt.date(),
            to_date=entry_dt.date(),
            interval="1minute",
        )
    except Exception as e:
        print(f"  Failed to fetch candles for {instrument_key}: {e}")
        return None
    if df.empty:
        return None
    df = df.sort_index()
    df = df[df.index >= entry_dt]
    if df.empty:
        return None
    return float(df.iloc[0]["close"])


def find_instrument_to_short(
    entry_datetime: str,
    target_premium: float,
    expiry_date: str,
    underlying_key: str,
    option_type: str,
    strike_gap: int = 100,
    tolerance: float = 50.0,
    token: str = "",
) -> tuple[str, int, float, float] | None:
    """
    Returns (instrument_key, lot_size, strike, premium_at_entry) or None if not found.
    option_type must be "CE" or "PE".
    """
    from get_instrument import get_expired_option_contracts

    entry_dt = pd.to_datetime(entry_datetime)
    if not token:
        token = _get_access_token()

    # 1. Underlying LTP at entry (1-min candles)
    ltp = get_underlying_ltp_at_entry(underlying_key, entry_dt, token)
    if ltp <= 0:
        return None

    # 2. Load contracts and filter by option_type
    contracts_df = get_expired_option_contracts(underlying_key, expiry_date)
    filtered = contracts_df[contracts_df["instrument_type"].str.upper() == option_type.upper()]
    if filtered.empty:
        print(f"ERROR: No {option_type} contracts for expiry {expiry_date}")
        return None

    # 3. Nearest strike and candidate order (by distance from LTP)
    nearest_strike = round(ltp / strike_gap) * strike_gap
    strikes_available = sorted(filtered["strike_price"].unique())
    candidate_strikes = sorted(strikes_available, key=lambda s: abs(s - ltp))

    # 4. Find strike whose premium at entry is within tolerance of target (or closest)
    best = None
    best_diff = float("inf")

    for strike in candidate_strikes:
        row = filtered[filtered["strike_price"] == strike].iloc[0]
        instrument_key = row["instrument_key"]
        lot_size = int(row["lot_size"])
        premium = get_option_premium_at_entry(instrument_key, entry_dt, token)
        if premium is None:
            continue
        diff = abs(premium - target_premium)
        if diff <= tolerance:
            print(f"Strike {strike} premium {premium:.2f} within tolerance of {target_premium}")
            return (instrument_key, lot_size, float(strike), premium)
        if diff < best_diff:
            best_diff = diff
            best = (instrument_key, lot_size, float(strike), premium)

    if best is not None:
        print(f"Using strike with closest premium: strike={best[2]}, premium={best[3]:.2f} (target={target_premium})")
        return best
    print("ERROR: No option data found for any candidate strike")
    return None


def _resolve_hedge_contract(
    underlying_key: str,
    expiry_date: str,
    option_type: str,
    short_strike: float,
    hedge_difference: int,
) -> tuple[str, int, float] | None:
    """
    Return (hedge_instrument_key, hedge_lot_size, hedge_strike).
    CE hedge (bear call spread): short_strike + hedge_difference
    PE hedge (bull put spread):  short_strike - hedge_difference
    Returns None if hedge strike not found.
    """
    from get_instrument import get_expired_option_contracts

    if option_type.upper() == "PE":
        hedge_strike = short_strike - hedge_difference
    else:
        hedge_strike = short_strike + hedge_difference
    contracts_df = get_expired_option_contracts(underlying_key, expiry_date)
    filtered = contracts_df[contracts_df["instrument_type"].str.upper() == option_type.upper()]
    match = filtered[filtered["strike_price"] == hedge_strike]
    if match.empty:
        return None
    row = match.iloc[0]
    return (row["instrument_key"], int(row["lot_size"]), float(hedge_strike))


def _fetch_underlying_ltp_series(
    underlying_key: str,
    entry_dt: pd.Timestamp,
    expiry_dt: pd.Timestamp,
    token: str,
) -> pd.Series:
    """
    Fetch underlying 1-minute candles from entry to expiry.
    Returns a Series (timestamp index -> close) so Phase 2 can look up LTP at any bar.
    """
    encoded_key = urllib.parse.quote(underlying_key, safe="")
    from_str = entry_dt.strftime("%Y-%m-%d")
    to_str = expiry_dt.strftime("%Y-%m-%d")
    url = f"{BASE_URL}/historical-candle/{encoded_key}/1minute/{to_str}/{from_str}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    resp = upstox_api.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        print(f"ERROR: Underlying LTP series API {resp.status_code}: {resp.text[:200]}")
        return pd.Series(dtype=float)
    data = resp.json()
    candles = data.get("data", {}).get("candles", [])
    if not candles:
        print(f"ERROR: No underlying candle data from {from_str} to {to_str}")
        return pd.Series(dtype=float)

    df = pd.DataFrame(candles)
    df["timestamp"] = pd.to_datetime(df[0])
    df["close"] = pd.to_numeric(df[4], errors="coerce")
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    df = df.sort_values("timestamp")
    df = df[(df["timestamp"] >= entry_dt) & (df["timestamp"] <= expiry_dt)]
    ser = df.set_index("timestamp")["close"]
    ser = ser[~ser.index.duplicated(keep="first")]
    print(f"Underlying LTP series: {len(ser)} bars from {ser.index.min()} to {ser.index.max()}")
    return ser


def _fetch_multi_strike_candles(
    underlying_key: str,
    expiry_date: str,
    entry_dt: pd.Timestamp,
    expiry_dt: pd.Timestamp,
    option_type: str,
    strike_gap: int,
    hedge_difference: int,
    strike_range: int,
    token: str,
    interval: str = "1minute",
) -> tuple[dict, dict, dict, dict]:
    """
    Pre-fetch candles for short and hedge for strikes in [ATM - strike_range*strike_gap, ATM + strike_range*strike_gap].
    Returns (short_candles, hedge_candles, short_lots, hedge_lots) each keyed by short_strike.
    """
    from get_instrument import get_expired_option_contracts
    from main import fetch_candle_data

    contracts_df = get_expired_option_contracts(underlying_key, expiry_date)
    filtered = contracts_df[contracts_df["instrument_type"].str.upper() == option_type.upper()]
    all_strikes = sorted(filtered["strike_price"].unique())
    atm = round(get_underlying_ltp_at_entry(underlying_key, entry_dt, token) / strike_gap) * strike_gap
    lo = atm - strike_range * strike_gap
    hi = atm + strike_range * strike_gap
    # PE hedge = short_strike - hedge_difference (bull put spread); CE hedge = short_strike + hedge_difference (bear call spread)
    if option_type.upper() == "PE":
        short_strikes = [s for s in all_strikes if lo <= s <= hi and (s - hedge_difference) in all_strikes]
    else:
        short_strikes = [s for s in all_strikes if lo <= s <= hi and (s + hedge_difference) in all_strikes]

    short_candles: dict[float, pd.DataFrame] = {}
    hedge_candles: dict[float, pd.DataFrame] = {}
    short_lots: dict[float, int] = {}
    hedge_lots: dict[float, int] = {}

    for strike in short_strikes:
        row_short = filtered[filtered["strike_price"] == strike].iloc[0]
        hedge_strike = strike - hedge_difference if option_type.upper() == "PE" else strike + hedge_difference
        row_hedge = filtered[filtered["strike_price"] == hedge_strike].iloc[0]
        short_key = row_short["instrument_key"]
        hedge_key = row_hedge["instrument_key"]
        short_lots[strike] = int(row_short["lot_size"])
        hedge_lots[strike] = int(row_hedge["lot_size"])
        try:
            df_short = fetch_candle_data(
                short_key,
                from_date=entry_dt.date(),
                to_date=expiry_dt.date(),
                interval=interval,
            )
            df_short = df_short[(df_short.index >= entry_dt) & (df_short.index <= expiry_dt)]
            short_candles[strike] = df_short[["close"]].copy()
        except Exception as e:
            print(f"  Skip strike {strike} {option_type} short: {e}")
            continue
        try:
            df_hedge = fetch_candle_data(
                hedge_key,
                from_date=entry_dt.date(),
                to_date=expiry_dt.date(),
                interval=interval,
            )
            df_hedge = df_hedge[(df_hedge.index >= entry_dt) & (df_hedge.index <= expiry_dt)]
            hedge_candles[strike] = df_hedge[["close"]].copy()
        except Exception as e:
            print(f"  Skip strike {strike} {option_type} hedge: {e}")
            continue

    return short_candles, hedge_candles, short_lots, hedge_lots


def run(
    entry_datetime: str,
    target_premium: float,
    expiry_date: str,
    underlying_key: str,
    option_type: str,
    strike_gap: int = 100,
    tolerance: float = 50.0,
    hedge_difference: int | None = None,
    square_off_short_below: float | None = None,
    output_excel: str = "backtest_results_fixed.xlsx",
    short_pair: bool = False,
    phase2_trigger_premium: float | None = None,
    phase2_target_reentry: float = 300.0,
    phase2_strike_range: int = 15,
    phase3_trigger_premium: float | None = None,
    phase3_target_reentry: float = 55.0,
    phase4_trigger_premium: float | None = None,
    phase4_target_reentry: float = 60.0,
    stoploss_amount: float | None = None,
) -> "pd.DataFrame | None":
    """
    Find instrument(s) to short and run backtest; save result to Excel.
    If short_pair is False: single option (option_type CE or PE), optional hedge, optional square_off.
    If short_pair is True: short CE + hedge CE + short PE + hedge PE at same entry/target; no square-off.
    If phase2_trigger_premium is not None (and short_pair and 4 legs): Phase 2 re-entry when short CE/PE > trigger.
    Returns the result DataFrame on success, or None on failure / no data.
    """
    import main

    token = _get_access_token()
    instruments: list[dict]

    if short_pair:
        # Pair mode: short CE + hedge CE + short PE + hedge PE
        print("Pair mode: finding CE to short...")
        ce_result = find_instrument_to_short(
            entry_datetime=entry_datetime,
            target_premium=target_premium,
            expiry_date=expiry_date,
            underlying_key=underlying_key,
            option_type="CE",
            strike_gap=strike_gap,
            tolerance=tolerance,
            token=token,
        )
        if ce_result is None:
            print("Aborting: could not find CE to short.")
            return None
        ce_key, ce_lot, strike_ce, premium_ce = ce_result
        print(f"Short CE: {ce_key} (strike={strike_ce}, lot_size={ce_lot}, entry premium={premium_ce:.2f})")

        instruments = [{"instrument_key": ce_key, "side": "SELL", "lot_size": ce_lot}]
        if hedge_difference:
            ce_hedge = _resolve_hedge_contract(
                underlying_key=underlying_key,
                expiry_date=expiry_date,
                option_type="CE",
                short_strike=strike_ce,
                hedge_difference=hedge_difference,
            )
            if ce_hedge is None:
                print(f"ERROR: CE hedge strike {strike_ce + hedge_difference} not found. Aborting.")
                sys.exit(1)
            hedge_ce_key, hedge_ce_lot, hedge_ce_strike = ce_hedge
            print(f"Hedge CE (long): {hedge_ce_key} (strike={hedge_ce_strike}, lot_size={hedge_ce_lot})")
            instruments.append({"instrument_key": hedge_ce_key, "side": "BUY", "lot_size": hedge_ce_lot})

        print("Pair mode: finding PE to short...")
        pe_result = find_instrument_to_short(
            entry_datetime=entry_datetime,
            target_premium=target_premium,
            expiry_date=expiry_date,
            underlying_key=underlying_key,
            option_type="PE",
            strike_gap=strike_gap,
            tolerance=tolerance,
            token=token,
        )
        if pe_result is None:
            print("Aborting: could not find PE to short.")
            return None
        pe_key, pe_lot, strike_pe, premium_pe = pe_result
        print(f"Short PE: {pe_key} (strike={strike_pe}, lot_size={pe_lot}, entry premium={premium_pe:.2f})")
        instruments.append({"instrument_key": pe_key, "side": "SELL", "lot_size": pe_lot})
        if hedge_difference:
            pe_hedge = _resolve_hedge_contract(
                underlying_key=underlying_key,
                expiry_date=expiry_date,
                option_type="PE",
                short_strike=strike_pe,
                hedge_difference=hedge_difference,
            )
            if pe_hedge is None:
                print(f"ERROR: PE hedge strike {strike_pe - hedge_difference} not found. Aborting.")
                sys.exit(1)
            hedge_pe_key, hedge_pe_lot, hedge_pe_strike = pe_hedge
            print(f"Hedge PE (long): {hedge_pe_key} (strike={hedge_pe_strike}, lot_size={hedge_pe_lot})")
            instruments.append({"instrument_key": hedge_pe_key, "side": "BUY", "lot_size": hedge_pe_lot})

        expiry_datetime = f"{expiry_date} 15:30:00"
        if phase2_trigger_premium is not None and len(instruments) == 4 and hedge_difference:
            # Phase 2: pre-fetch multi-strike candles and run stateful backtest with re-entry
            entry_dt = pd.to_datetime(entry_datetime)
            expiry_dt = pd.to_datetime(expiry_datetime)
            print("Phase 2: fetching underlying LTP series...")
            underlying_ltp_series = _fetch_underlying_ltp_series(
                underlying_key=underlying_key,
                entry_dt=entry_dt,
                expiry_dt=expiry_dt,
                token=token,
            )
            print("Phase 2: fetching multi-strike candles for CE...")
            ce_short_candles, ce_hedge_candles, ce_short_lots, ce_hedge_lots = _fetch_multi_strike_candles(
                underlying_key=underlying_key,
                expiry_date=expiry_date,
                entry_dt=entry_dt,
                expiry_dt=expiry_dt,
                option_type="CE",
                strike_gap=strike_gap,
                hedge_difference=hedge_difference,
                strike_range=phase2_strike_range,
                token=token,
                interval="1minute",
            )
            print("Phase 2: fetching multi-strike candles for PE...")
            pe_short_candles, pe_hedge_candles, pe_short_lots, pe_hedge_lots = _fetch_multi_strike_candles(
                underlying_key=underlying_key,
                expiry_date=expiry_date,
                entry_dt=entry_dt,
                expiry_dt=expiry_dt,
                option_type="PE",
                strike_gap=strike_gap,
                hedge_difference=hedge_difference,
                strike_range=phase2_strike_range,
                token=token,
                interval="1minute",
            )
            if strike_ce not in ce_short_candles or strike_pe not in pe_short_candles:
                print("ERROR: Initial strikes not in Phase 2 strike range. Run without Phase 2 or increase PHASE2_STRIKE_RANGE.")
                result_df = main.run_weekly_backtest(
                    instruments=instruments,
                    entry_datetime=entry_datetime,
                    expiry_datetime=expiry_datetime,
                    square_off_short_below=None,
                )
            else:
                result_df = main.run_weekly_backtest_phase2(
                    entry_datetime=entry_datetime,
                    expiry_datetime=expiry_datetime,
                    initial_ce_short_strike=strike_ce,
                    initial_pe_short_strike=strike_pe,
                    trigger_premium=phase2_trigger_premium,
                    target_reentry_premium=phase2_target_reentry,
                    hedge_difference=hedge_difference,
                    ce_short_candles=ce_short_candles,
                    ce_hedge_candles=ce_hedge_candles,
                    pe_short_candles=pe_short_candles,
                    pe_hedge_candles=pe_hedge_candles,
                    ce_short_lots=ce_short_lots,
                    ce_hedge_lots=ce_hedge_lots,
                    pe_short_lots=pe_short_lots,
                    pe_hedge_lots=pe_hedge_lots,
                    underlying_ltp_series=underlying_ltp_series,
                    strike_gap=strike_gap,
                    strike_range=phase2_strike_range,
                    phase3_trigger_premium=phase3_trigger_premium,
                    phase3_target_reentry=phase3_target_reentry,
                    phase4_trigger_premium=phase4_trigger_premium,
                    phase4_target_reentry=phase4_target_reentry,
                    stoploss_amount=stoploss_amount,
                )
        else:
            result_df = main.run_weekly_backtest(
                instruments=instruments,
                entry_datetime=entry_datetime,
                expiry_datetime=expiry_datetime,
                square_off_short_below=None,
            )
    else:
        # Single-option mode
        result = find_instrument_to_short(
            entry_datetime=entry_datetime,
            target_premium=target_premium,
            expiry_date=expiry_date,
            underlying_key=underlying_key,
            option_type=option_type,
            strike_gap=strike_gap,
            tolerance=tolerance,
            token=token,
        )
        if result is None:
            print("Aborting: could not find instrument to short.")
            return None

        instrument_key, lot_size, strike, premium = result
        print(f"Instrument to short: {instrument_key} (strike={strike}, lot_size={lot_size}, entry premium={premium:.2f})")

        instruments = [
            {"instrument_key": instrument_key, "side": "SELL", "lot_size": lot_size},
        ]
        if hedge_difference:
            hedge_result = _resolve_hedge_contract(
                underlying_key=underlying_key,
                expiry_date=expiry_date,
                option_type=option_type,
                short_strike=strike,
                hedge_difference=hedge_difference,
            )
            if hedge_result is None:
                h_strike = strike - hedge_difference if option_type.upper() == "PE" else strike + hedge_difference
                print(f"ERROR: Hedge strike {h_strike} not found for expiry {expiry_date}. Aborting.")
                sys.exit(1)
            hedge_instrument_key, hedge_lot_size, hedge_strike_val = hedge_result
            print(f"Hedge (long): {hedge_instrument_key} (strike={hedge_strike_val}, lot_size={hedge_lot_size})")
            instruments.append(
                {"instrument_key": hedge_instrument_key, "side": "BUY", "lot_size": hedge_lot_size},
            )

        expiry_datetime = f"{expiry_date} 15:30:00"
        result_df = main.run_weekly_backtest(
            instruments=instruments,
            entry_datetime=entry_datetime,
            expiry_datetime=expiry_datetime,
            square_off_short_below=square_off_short_below,
        )

    if result_df.empty:
        print("Backtest returned no data.")
        return None

    # Rename columns for clearer Excel headers
    if len(instruments) == 2 and not short_pair:
        rename = {}
        for col in result_df.columns:
            if col == "total_pnl":
                continue
            if col.startswith("close_") and col.endswith("_0"):
                rename[col] = "short_close"
            elif col.startswith("close_") and col.endswith("_1"):
                rename[col] = "hedge_close"
            elif col.startswith("pnl_") and col.endswith("_0"):
                rename[col] = "short_pnl"
            elif col.startswith("pnl_") and col.endswith("_1"):
                rename[col] = "hedge_pnl"
        result_df = result_df.rename(columns=rename)
    elif len(instruments) == 2 and short_pair:
        # Pair mode with no hedge: short CE (0), short PE (1)
        rename = {}
        for col in result_df.columns:
            if col == "total_pnl":
                continue
            if col.startswith("close_") and col.endswith("_0"):
                rename[col] = "short_ce_close"
            elif col.startswith("close_") and col.endswith("_1"):
                rename[col] = "short_pe_close"
            elif col.startswith("pnl_") and col.endswith("_0"):
                rename[col] = "short_ce_pnl"
            elif col.startswith("pnl_") and col.endswith("_1"):
                rename[col] = "short_pe_pnl"
        result_df = result_df.rename(columns=rename)
    elif len(instruments) == 4:
        rename = {}
        for col in result_df.columns:
            if col == "total_pnl":
                continue
            if col.startswith("close_") and col.endswith("_0"):
                rename[col] = "short_ce_close"
            elif col.startswith("close_") and col.endswith("_1"):
                rename[col] = "hedge_ce_close"
            elif col.startswith("close_") and col.endswith("_2"):
                rename[col] = "short_pe_close"
            elif col.startswith("close_") and col.endswith("_3"):
                rename[col] = "hedge_pe_close"
            elif col.startswith("pnl_") and col.endswith("_0"):
                rename[col] = "short_ce_pnl"
            elif col.startswith("pnl_") and col.endswith("_1"):
                rename[col] = "hedge_ce_pnl"
            elif col.startswith("pnl_") and col.endswith("_2"):
                rename[col] = "short_pe_pnl"
            elif col.startswith("pnl_") and col.endswith("_3"):
                rename[col] = "hedge_pe_pnl"
        result_df = result_df.rename(columns=rename)

    if output_excel is not None:
        result_df.to_excel(output_excel, index=True)
        print(f"Results saved to {output_excel}")

    return result_df


if __name__ == "__main__":
    run(
        entry_datetime=ENTRY_DATETIME,
        target_premium=TARGET_PREMIUM,
        expiry_date=EXPIRY_DATE,
        underlying_key=UNDERLYING_KEY,
        option_type=OPTION_TYPE,
        strike_gap=STRIKE_GAP,
        tolerance=TOLERANCE,
        hedge_difference=HEDGE_DIFFERENCE,
        square_off_short_below=SQUARE_OFF_WHEN_SHORT_BELOW,
        output_excel=OUTPUT_EXCEL,
        short_pair=SHORT_PAIR,
        phase2_trigger_premium=PHASE2_TRIGGER_PREMIUM,
        phase2_target_reentry=PHASE2_TARGET_REENTRY,
        phase2_strike_range=PHASE2_STRIKE_RANGE,
        phase3_trigger_premium=PHASE3_TRIGGER_PREMIUM,
        phase3_target_reentry=PHASE3_TARGET_REENTRY,
        phase4_trigger_premium=PHASE4_TRIGGER_PREMIUM,
        phase4_target_reentry=PHASE4_TARGET_REENTRY,
        stoploss_amount=STOPLOSS_AMOUNT,
    )
