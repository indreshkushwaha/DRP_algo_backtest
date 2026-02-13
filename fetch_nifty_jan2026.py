from __future__ import annotations

"""
Fetch NIFTY 26000 Jan 2026 Expiry Data
======================================
Retrieves daily candle data for NIFTY 26000 CE/PE options
expiring on 29th Jan 2026.
"""

import os
import sys
import urllib.parse
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from tabulate import tabulate

# ── Configuration ────────────────────────────────────────────────────────────
BASE_URL = "https://api.upstox.com/v2"
INSTRUMENT_KEY_UNDERLYING = "NSE_INDEX|Nifty 50"
TARGET_EXPIRY = "2026-01-27"  # NIFTY Jan 2026 Monthly Expiry (Tuesday)
TARGET_STRIKE = 26000
DATA_START_DATE = "2025-05-01"  # Fetch data from start of Jan


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_access_token() -> str:
    """Load access token from .env file."""
    load_dotenv()
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token or token == "your_access_token_here":
        print("❌ ERROR: Please set your UPSTOX_ACCESS_TOKEN in the .env file.")
        sys.exit(1)
    return token


def make_request(url: str, params: dict | None = None, token: str = "") -> dict:
    """Make an authenticated GET request."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    try:
        # Debug: check if params has instrument_key
        # print(f"DEBUG: Calling {url} with {params}")
        
        response = requests.get(url, params=params, headers=headers, timeout=30)
        
        if response.status_code == 403:
             print("\n🚫 ACCESS DENIED (403): You might need an 'Upstox Plus' subscription.")
             return {}
        
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return {}


def get_expired_contracts(expiry_date: str, token: str) -> list[dict]:
    """Fetch expired option contracts."""
    url = f"{BASE_URL}/expired-instruments/option/contract"
    
    # Try the standard key first
    keys_to_try = [INSTRUMENT_KEY_UNDERLYING, "NSE_INDEX|NIFTY 50"]
    
    for key in keys_to_try:
        params = {
            "instrument_key": key,
            "expiry_date": expiry_date,
        }
        print(f"   Fetching contracts for expiry: {expiry_date} (Key: {key})...")
        
        data = make_request(url, params, token)
        contracts = data.get("data", [])
        
        if contracts:
            print(f"✅ Success! Found {len(contracts)} contracts.")
            return contracts
            
    print(f"⚠  No contracts found for {expiry_date} with any key variant.")
    return []


def get_historical_candles_range(contract: dict, start_date: str, end_date: str, token: str):
    """Fetch daily candles for the specific contract within date range."""
    name = contract.get('trading_symbol')
    instrument_key = contract.get('instrument_key')
    encoded_key = urllib.parse.quote(instrument_key, safe='')
    
    interval = "day"  # Daily candles
    
    # Endpoint format: .../historical-candle/{instrumentKey}/{interval}/{to_date}/{from_date}
    # Note: Upstox API expects 'to_date' then 'from_date' in path
    url = f"{BASE_URL}/expired-instruments/historical-candle/{encoded_key}/{interval}/{end_date}/{start_date}"
    
    print(f"\n   Requesting DAILY candles for {name} ({start_date} to {end_date})...")
    data = make_request(url, token=token)
    
    candles = data.get("data", {}).get("candles", [])
    if not candles:
        print("   ⚠ No candles returned.")
        return

    print(f"   ✅ Retrieved {len(candles)} daily candles.")
    
    # Display table
    headers = ["Date", "Open", "High", "Low", "Close", "Vol", "OI"]
    table_data = []
    
    # Sort by time
    candles.sort(key=lambda x: x[0])
    
    for c in candles:
        # Timestamp: "2026-01-01T00:00:00+05:30" -> "2026-01-01"
        date_str = c[0].split('T')[0]
        row = [
            date_str,
            f"{c[1]:.2f}",
            f"{c[2]:.2f}",
            f"{c[3]:.2f}",
            f"{c[4]:.2f}",
            f"{c[5]:,}",
            f"{c[6]:,}"
        ]
        table_data.append(row)
        
    print(tabulate(table_data, headers=headers, tablefmt="rounded_outline", stralign="right"))


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "═" * 60)
    print(f"  Fetching NIFTY {TARGET_STRIKE} Jan 2026 Expired Data")
    print("═" * 60)
    
    token = load_access_token()
    
    # 1. Get contracts for 2026-01-29
    contracts = get_expired_contracts(TARGET_EXPIRY, token)
    if not contracts:
        print("No contracts found.")
        return

    # 2. Filter for Strike 26000
    targets = [
        c for c in contracts 
        if c.get('strike_price') == TARGET_STRIKE 
        and c.get('instrument_type') in ('CE', 'PE')
    ]
    
    if not targets:
        print(f"❌ No contracts found for Strike {TARGET_STRIKE} on {TARGET_EXPIRY}")
        return

    print(f"✅ Found {len(targets)} contracts for Strike {TARGET_STRIKE}.")

    # 3. Fetch data for each (CE and PE)
    for contract in targets:
        get_historical_candles_range(contract, DATA_START_DATE, TARGET_EXPIRY, token)


if __name__ == "__main__":
    main()
