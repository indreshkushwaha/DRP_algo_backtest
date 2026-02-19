from __future__ import annotations

"""
Sensex ATM Straddle Backtest
============================
Backtests selling an ATM Straddle (Sell CE + Sell PE) on Sensex
at a specific Entry Date & Time.
Calculates Minute-by-Minute PnL.

Usage:
    1. Update CONFIGURATION section below
    2. python sensex_backtest.py
"""

import os
import sys
import urllib.parse
from datetime import datetime, timedelta

import requests
import pandas as pd
from tabulate import tabulate

from get_token import require_access_token

# ── Configuration ────────────────────────────────────────────────────────────
# UPDATE THESE VALUES
EXPIRY_DATE = "2026-01-09"         # Example Expiry (Friday?)
ENTRY_DATETIME = "2026-01-09 09:20:00"  # Entry Date & Time

# Sensex Details
INSTRUMENT_KEY_SPOT = "BSE_INDEX|SENSEX"
LOT_SIZE = 10
STRIKE_GAP = 100


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_access_token() -> str:
    """Load access token from token_config.py."""
    return require_access_token()


def make_request(url: str, params: dict | None = None, token: str = "") -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        
        if response.status_code == 403:
             print("\n🚫 ACCESS DENIED (403): Requires Upstox Plus (Expired API) or Valid Token.")
             return {}
             
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            print(f"❌ HTTP ERROR: {e}")
            print(f"   Response Text: {response.text}")
            return {}
            
        return response.json()
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return {}


# ── Data Fetching ────────────────────────────────────────────────────────────

def get_spot_price(entry_dt: datetime, token: str) -> float:
    """Fetch Spot Price at Entry Time."""
    date_str = entry_dt.strftime("%Y-%m-%d")
    encoded_key = urllib.parse.quote(INSTRUMENT_KEY_SPOT, safe='')
    
    # Use standard historical API for ongoing instruments like Indices
    # Note: Indices don't expire, so we use the regular endpoint
    url = f"https://api.upstox.com/v2/historical-candle/{encoded_key}/1minute/{date_str}/{date_str}"
    
    print(f"   Fetching Spot Data for {date_str}...")
    data = make_request(url, token=token)
    candles = data.get("data", {}).get("candles", [])
    
    if not candles:
        print("❌ No spot data found.")
        return 0.0
    
    # Convert to DataFrame
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "vol", "oi"])
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_convert(None) # Remove timezone for comparison
    
    # Find candle matching entry time (or nearest before)
    target_time = entry_dt.replace(second=0, microsecond=0)
    row = df[df["timestamp"] == target_time]
    
    if row.empty:
        print(f"❌ No spot data found for exact time {target_time}. Using nearest...")
        # Fallback logic if needed, but for backtest exact is better
        return 0.0
        
    spot = row.iloc[0]["close"]
    print(f"✅ Spot Price at {target_time}: {spot}")
    return spot


def get_contracts(expiry_date: str, strike: int, token: str) -> dict:
    """Find CE and PE contract keys for the given Strike and Expiry."""
    url = "https://api.upstox.com/v2/expired-instruments/option/contract"
    params = {
        "instrument_key": INSTRUMENT_KEY_SPOT,
        "expiry_date": expiry_date,
    }
    
    print(f"   Fetching Contracts for Expiry: {expiry_date}...")
    data = make_request(url, params, token)
    all_contracts = data.get("data", [])
    
    ce_contract = None
    pe_contract = None
    
    for c in all_contracts:
        if c.get("strike_price") == strike and c.get("instrument_type") == "CE":
            ce_contract = c
        elif c.get("strike_price") == strike and c.get("instrument_type") == "PE":
            pe_contract = c
            
    if not ce_contract or not pe_contract:
        print(f"❌ Could not find both CE and PE contracts for Strike {strike}.")
        return {}
        
    print(f"✅ Found Contracts for Strike {strike}:")
    print(f"   CE: {ce_contract['trading_symbol']}")
    print(f"   PE: {pe_contract['trading_symbol']}")
    
    return {"CE": ce_contract, "PE": pe_contract}


def get_candle_data(contract: dict, date_str: str, token: str) -> pd.DataFrame:
    """Fetch 1-minute candles for an option contract."""
    key = contract.get("instrument_key")
    encoded_key = urllib.parse.quote(key, safe='')
    url = f"https://api.upstox.com/v2/expired-instruments/historical-candle/{encoded_key}/1minute/{date_str}/{date_str}"
    
    data = make_request(url, token=token)
    candles = data.get("data", {}).get("candles", [])
    
    if not candles:
        return pd.DataFrame()
        
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "vol", "oi"])
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_convert(None)
    return df[["timestamp", "close"]]


# ── Backtest Logic ───────────────────────────────────────────────────────────

def run_backtest():
    print("\n" + "═" * 60)
    print("  SENSEX ATM STRADDLE BACKTEST")
    print("═" * 60)
    
    token = load_access_token()
    entry_dt = datetime.strptime(ENTRY_DATETIME, "%Y-%m-%d %H:%M:%S")
    date_str = entry_dt.strftime("%Y-%m-%d")
    
    # 1. Get Spot Price
    spot_price = get_spot_price(entry_dt, token)
    if spot_price == 0:
        return
        
    # 2. Identify ATM Strike
    atm_strike = round(spot_price / STRIKE_GAP) * STRIKE_GAP
    print(f"   ATM Strike: {atm_strike}")
    
    # 3. Get Contracts
    contracts = get_contracts(EXPIRY_DATE, atm_strike, token)
    if not contracts:
        return
        
    # 4. Fetch Option Data
    print(f"   Fetching Option Candles...")
    ce_df = get_candle_data(contracts["CE"], date_str, token)
    pe_df = get_candle_data(contracts["PE"], date_str, token)
    
    if ce_df.empty or pe_df.empty:
        print("❌ Missing data for CE or PE.")
        return

    # 5. Process Data (Merge)
    # Rename columns
    ce_df = ce_df.rename(columns={"close": "ce_close"})
    pe_df = pe_df.rename(columns={"close": "pe_close"})
    
    # Merge on timestamp
    df = pd.merge(ce_df, pe_df, on="timestamp", how="inner")
    
    # Filter for time >= Entry Time
    df = df[df["timestamp"] >= entry_dt].sort_values("timestamp").reset_index(drop=True)
    
    if df.empty:
        print("❌ No data found after Entry Time.")
        return
        
    # 6. Calculate PnL
    # Sell Price = Close price at first candle (Entry)
    entry_ce = df.iloc[0]["ce_close"]
    entry_pe = df.iloc[0]["pe_close"]
    
    print(f"\n   ENTRY EXECUTED at {df.iloc[0]['timestamp']}")
    print(f"   Sold CE at: {entry_ce}")
    print(f"   Sold PE at: {entry_pe}")
    print(f"   Total Premium: {entry_ce + entry_pe}")
    
    # PnL (Short) = Entry Price - Current Price
    df["ce_pnl"] = (entry_ce - df["ce_close"])
    df["pe_pnl"] = (entry_pe - df["pe_close"])
    df["net_pnl"] = df["ce_pnl"] + df["pe_pnl"]
    
    # Net PnL (Total Points)
    
    # 7. Display
    print("\n   MINUTE-BY-MINUTE PnL (Points):")
    
    # Format for display
    display_df = df.copy()
    display_df["Time"] = display_df["timestamp"].dt.strftime("%H:%M")
    display_df["Spot"] = "—" # We could merge spot df too if we kept it
    
    table_headers = ["Time", "CE Price", "PE Price", "CE PnL", "PE PnL", "NET PnL"]
    table_data = []
    
    for _, row in display_df.iterrows():
        table_data.append([
            row["Time"],
            f"{row['ce_close']:.2f}",
            f"{row['pe_close']:.2f}",
            f"{row['ce_pnl']:.2f}",
            f"{row['pe_pnl']:.2f}",
            f"{row['net_pnl']:.2f}"
        ])
        
    print(tabulate(table_data, headers=table_headers, tablefmt="rounded_outline", stralign="right"))
    
    final_pnl = df.iloc[-1]["net_pnl"]
    print(f"\n   🏁 FINAL NET PnL: {final_pnl:.2f} points (x {LOT_SIZE} qty = ₹{final_pnl * LOT_SIZE:.2f})")


if __name__ == "__main__":
    run_backtest()
