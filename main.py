import requests
import pandas as pd
import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.upstox.com/v2"
ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()


def fetch_candle_data(instrument_key, from_date, to_date, interval="5minute"):
    """
    Fetch historical candles from Upstox
    interval: 1minute, 5minute, 10minute, 30minute, 60minute, day, week, month
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
    expiry_datetime
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
                interval="5minute"
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
    underlying_ltp_series: pd.Series | None = None,
    strike_gap: int = 100,
    strike_range: int = 15,
):
    """
    Stateful backtest with Phase 2: when short CE > trigger, cover put pair and re-enter put at premium ~ target; when short PE > trigger, cover call pair and re-enter call at premium ~ target. Uses LTP at re-entry to restrict strikes around ATM. Returns DataFrame with closes, PnLs, and short_ce_strike, short_pe_strike per bar.
    """
    entry_dt = pd.to_datetime(entry_datetime)
    expiry_dt = pd.to_datetime(expiry_datetime)
    if initial_ce_short_strike not in ce_short_candles or initial_pe_short_strike not in pe_short_candles:
        return pd.DataFrame()
    idx_ce = ce_short_candles[initial_ce_short_strike].index
    idx_pe = pe_short_candles[initial_pe_short_strike].index
    timeline = idx_ce.union(idx_pe).sort_values()
    timeline = timeline[(timeline >= entry_dt) & (timeline <= expiry_dt)]
    if underlying_ltp_series is not None and not underlying_ltp_series.empty:
        ltp_filled = underlying_ltp_series.reindex(timeline, method="ffill")
    else:
        ltp_filled = None

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
    print(f"[Phase2] Backtest: entry={entry_dt} to expiry={expiry_dt}, trigger={trigger_premium}, re-entry target={target_reentry_premium}")

    ce_short_strike = initial_ce_short_strike
    pe_short_strike = initial_pe_short_strike
    entry_ce_short = entry_ce_hedge = entry_pe_short = entry_pe_hedge = None
    cumulative_realized = 0.0
    rows = []
    reentry_ce = reentry_pe = 0

    for ts in timeline:
        close_ce_short = ce_short_filled.get(ce_short_strike)
        close_ce_short = close_ce_short.loc[ts] if close_ce_short is not None and ts in close_ce_short.index else None
        close_ce_hedge = ce_hedge_filled.get(ce_short_strike)
        close_ce_hedge = close_ce_hedge.loc[ts] if close_ce_hedge is not None and ts in close_ce_hedge.index else None
        close_pe_short = pe_short_filled.get(pe_short_strike)
        close_pe_short = close_pe_short.loc[ts] if close_pe_short is not None and ts in close_pe_short.index else None
        close_pe_hedge = pe_hedge_filled.get(pe_short_strike)
        close_pe_hedge = close_pe_hedge.loc[ts] if close_pe_hedge is not None and ts in close_pe_hedge.index else None
        if pd.isna(close_ce_short): close_ce_short = entry_ce_short
        if pd.isna(close_ce_hedge): close_ce_hedge = entry_ce_hedge
        if pd.isna(close_pe_short): close_pe_short = entry_pe_short
        if pd.isna(close_pe_hedge): close_pe_hedge = entry_pe_hedge
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

        if close_ce_short is not None and float(close_ce_short) > trigger_premium:
            c_pe = float(close_pe_short) if close_pe_short is not None else entry_pe_short
            c_pe_h = float(close_pe_hedge) if close_pe_hedge is not None else entry_pe_hedge
            round_pnl = (entry_pe_short - c_pe) * lot_pe_short + (c_pe_h - entry_pe_hedge) * lot_pe_hedge if entry_pe_short is not None else 0.0
            cumulative_realized += round_pnl
            ltp_ts = float(ltp_filled.loc[ts]) if ltp_filled is not None and ts in ltp_filled.index and not pd.isna(ltp_filled.loc[ts]) else None
            atm_ts = round(ltp_ts / strike_gap) * strike_gap if ltp_ts is not None else None
            lo_pe = (atm_ts - strike_range * strike_gap) if atm_ts is not None else None
            hi_pe = (atm_ts + strike_range * strike_gap) if atm_ts is not None else None
            candidates_pe = [s for s in pe_short_candles if (lo_pe is None or hi_pe is None or (lo_pe <= s <= hi_pe)) and s in pe_short_filled and s in pe_hedge_filled]
            best_pe = None
            best_diff = float("inf")
            for s in candidates_pe:
                val = pe_short_filled[s].loc[ts] if ts in pe_short_filled[s].index else None
                if pd.isna(val): continue
                diff = abs(float(val) - target_reentry_premium)
                if diff < best_diff: best_diff, best_pe = diff, s
            if best_pe is not None:
                new_prem = float(pe_short_filled[best_pe].loc[ts]) if ts in pe_short_filled[best_pe].index else None
                print(f"[Phase2] Cover put pair: ts={ts}, short_ce_close={float(close_ce_short):.2f}, realized_pnl={round_pnl:.2f}, LTP={ltp_ts}, ATM={atm_ts}, new PE strike={best_pe}, new PE premium={new_prem}")
                pe_short_strike = best_pe
                entry_pe_short = float(pe_short_filled[best_pe].loc[ts]) if ts in pe_short_filled[best_pe].index else entry_pe_short
                entry_pe_hedge = float(pe_hedge_filled[best_pe].loc[ts]) if ts in pe_hedge_filled[best_pe].index else entry_pe_hedge
                close_pe_short, close_pe_hedge = entry_pe_short, entry_pe_hedge
                lot_pe_short, lot_pe_hedge = pe_short_lots.get(pe_short_strike, lot_pe_short), pe_hedge_lots.get(pe_short_strike, lot_pe_hedge)
                reentry_pe += 1

        if close_pe_short is not None and float(close_pe_short) > trigger_premium:
            c_ce = float(close_ce_short) if close_ce_short is not None else entry_ce_short
            c_ce_h = float(close_ce_hedge) if close_ce_hedge is not None else entry_ce_hedge
            round_pnl = (entry_ce_short - c_ce) * lot_ce_short + (c_ce_h - entry_ce_hedge) * lot_ce_hedge if entry_ce_short is not None else 0.0
            cumulative_realized += round_pnl
            ltp_ts = float(ltp_filled.loc[ts]) if ltp_filled is not None and ts in ltp_filled.index and not pd.isna(ltp_filled.loc[ts]) else None
            atm_ts = round(ltp_ts / strike_gap) * strike_gap if ltp_ts is not None else None
            lo_ce = (atm_ts - strike_range * strike_gap) if atm_ts is not None else None
            hi_ce = (atm_ts + strike_range * strike_gap) if atm_ts is not None else None
            candidates_ce = [s for s in ce_short_candles if (lo_ce is None or hi_ce is None or (lo_ce <= s <= hi_ce)) and s in ce_short_filled and s in ce_hedge_filled]
            best_ce = None
            best_diff = float("inf")
            for s in candidates_ce:
                val = ce_short_filled[s].loc[ts] if ts in ce_short_filled[s].index else None
                if pd.isna(val): continue
                diff = abs(float(val) - target_reentry_premium)
                if diff < best_diff: best_diff, best_ce = diff, s
            if best_ce is not None:
                new_prem = float(ce_short_filled[best_ce].loc[ts]) if ts in ce_short_filled[best_ce].index else None
                print(f"[Phase2] Cover call pair: ts={ts}, short_pe_close={float(close_pe_short):.2f}, realized_pnl={round_pnl:.2f}, LTP={ltp_ts}, ATM={atm_ts}, new CE strike={best_ce}, new CE premium={new_prem}")
                ce_short_strike = best_ce
                entry_ce_short = float(ce_short_filled[best_ce].loc[ts]) if ts in ce_short_filled[best_ce].index else entry_ce_short
                entry_ce_hedge = float(ce_hedge_filled[best_ce].loc[ts]) if ts in ce_hedge_filled[best_ce].index else entry_ce_hedge
                close_ce_short, close_ce_hedge = entry_ce_short, entry_ce_hedge
                lot_ce_short, lot_ce_hedge = ce_short_lots.get(ce_short_strike, lot_ce_short), ce_hedge_lots.get(ce_short_strike, lot_ce_hedge)
                reentry_ce += 1

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
        pnl_ce_short = (e_ce_s - c_ce_s) * lot_ce_short
        pnl_ce_hedge = (c_ce_h - e_ce_h) * lot_ce_hedge
        pnl_pe_short = (e_pe_s - c_pe_s) * lot_pe_short
        pnl_pe_hedge = (c_pe_h - e_pe_h) * lot_pe_hedge
        total_pnl = cumulative_realized + pnl_ce_short + pnl_ce_hedge + pnl_pe_short + pnl_pe_hedge
        rows.append({
            "short_ce_close": c_ce_s,
            "hedge_ce_close": c_ce_h,
            "short_pe_close": c_pe_s,
            "hedge_pe_close": c_pe_h,
            "short_ce_strike": ce_short_strike,
            "short_pe_strike": pe_short_strike,
            "short_ce_pnl": pnl_ce_short,
            "hedge_ce_pnl": pnl_ce_hedge,
            "short_pe_pnl": pnl_pe_short,
            "hedge_pe_pnl": pnl_pe_hedge,
            "total_pnl": total_pnl,
        })

    result_df = pd.DataFrame(rows, index=timeline)
    result_df.index.name = "timestamp"
    print(f"[Phase2] Done: reentry_ce={reentry_ce}, reentry_pe={reentry_pe}")
    return result_df


instruments = [
    {"instrument_key": "BSE_FO|1140804|29-07-2025", "side": "SELL", "lot_size": 20},
    {"instrument_key": "BSE_FO|1175477|29-07-2025", "side": "SELL", "lot_size": 20},
    {"instrument_key": "BSE_FO|1140462|29-07-2025", "side": "SELL", "lot_size": 20},
]

result_df = run_weekly_backtest(
    instruments=instruments,
    entry_datetime="2025-07-25 09:20:00",
    expiry_datetime="2025-07-29 15:30:00"
)

result_df.to_excel("backtest_results_fixed.xlsx")
print("Results saved to backtest_results_fixed.xlsx")
