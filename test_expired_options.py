from __future__ import annotations

"""
Upstox Expired Options Test Script
===================================
Tests access to historical data for expired options (NIFTY 50).
Verifies the 'Expired Instruments API' (requires Upstox Plus).

Usage:
    1. Paste your access token in `.env`
    2. python test_expired_options.py
"""

import os
import sys
from datetime import datetime, timedelta
import urllib.parse

import requests
from dotenv import load_dotenv
from tabulate import tabulate

# ── Configuration ────────────────────────────────────────────────────────────
BASE_URL = "https://api.upstox.com/v2"
INSTRUMENT_NAME = "Nifty 50"
INSTRUMENT_KEY_UNDERLYING = "NSE_INDEX|Nifty 50"


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
        response = requests.get(url, params=params, headers=headers, timeout=30)
        
        if response.status_code == 403:
             print("\n🚫 ACCESS DENIED (403): You might need an 'Upstox Plus' subscription")
             print("   to access Expired Instruments API endpoints.")
             return {}
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP ERROR: {e}")
        return {}
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return {}


def get_last_expired_thursday() -> str:
    """Find the most recent past Thursday."""
    today = datetime.now().date()
    # Days to subtract to get to the most recent Thursday (0=Mon, 3=Thu)
    offset = (today.weekday() - 3) % 7
    most_recent_thursday = today - timedelta(days=offset)
    
    # If today is Thursday, we want the PREVIOUS one to be sure it's fully expired
    if most_recent_thursday >= today:
        most_recent_thursday -= timedelta(weeks=1)
        
    return most_recent_thursday.strftime("%Y-%m-%d")


def print_banner(title: str):
    """Print a formatted section banner."""
    print("\n" + "═" * 60)
    print(f"  {title}")
    print("═" * 60)


# ── Step 1: Fetch Expired Contracts ──────────────────────────────────────────

def get_expired_contracts(expiry_date: str, token: str) -> list[dict]:
    """Fetch expired option contracts for the given expiry date."""
    print_banner(f"STEP 1: Fetch Expired Contracts ({expiry_date})")
    
    endpoint = "/expired-instruments/option/contract"
    url = f"{BASE_URL}{endpoint}"
    params = {
        "instrument_key": INSTRUMENT_KEY_UNDERLYING,
        "expiry_date": expiry_date,
    }
    
    print(f"   Fetching contracts for expiry: {expiry_date}...")
    data = make_request(url, params, token)
    
    if not data or data.get("status") != "success":
        print("❌ Failed to fetch expired contracts.")
        return []
        
    contracts = data.get("data", [])
    print(f"✅ Success! Found {len(contracts)} expired contracts.")
    return contracts


# ── Step 2: Fetch Historical Candles ─────────────────────────────────────────

def get_historical_candles(contract: dict, expiry_date: str, token: str):
    """Fetch 30-minute candles for the specific contract on its expiry day."""
    name = contract.get('trading_symbol')
    instrument_key = contract.get('instrument_key')
    
    # Encode key just in case (e.g. pipes replacement)
    # The API documentation says pass instrument_key as path param.
    # We must URL-encode it because it contains '|'.
    encoded_key = urllib.parse.quote(instrument_key, safe='')
    
    print_banner(f"STEP 2: Historical Data for {name}")
    print(f"   Instrument Key: {instrument_key}")
    
    # We want data for the expiry day only
    from_date = expiry_date
    to_date = expiry_date
    interval = "30minute"  # 1minute, 30minute, day, etc.
    
    endpoint = f"/expired-instruments/historical-candle/{encoded_key}/{interval}/{to_date}/{from_date}"
    url = f"{BASE_URL}{endpoint}"
    
    print(f"   Requesting candles ({interval}) for {expiry_date}...")
    data = make_request(url, token=token)
    
    if not data or data.get("status") != "success":
        print("❌ Failed to fetch historical candles.")
        return

    candles = data.get("data", {}).get("candles", [])
    if not candles:
        print("⚠ No candles returned (data might be missing for this specific contract).")
        return

    print(f"✅ Success! Retrieved {len(candles)} candles.\n")
    
    # Display table
    # Candle format: [timestamp, open, high, low, close, volume, oi]
    headers = ["Time", "Open", "High", "Low", "Close", "Vol", "OI"]
    table_data = []
    
    # Sort by time (API usually returns reverse chronological, but let's be sure)
    candles.sort(key=lambda x: x[0])
    
    for c in candles:
        # Timestamp is usually ISO string "YYYY-MM-DDTHH:MM:SS+05:30"
        ts = c[0].split('T')[1].split('+')[0]  # Just HH:MM:SS
        row = [
            ts,
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
    print("\n🚀 Starting Upstox Expired Options Test...")
    token = load_access_token()
    
    # 1. Determine expiry date (last Thursday)
    expiry_date = get_last_expired_thursday()
    
    # 2. Get contracts
    contracts = get_expired_contracts(expiry_date, token)
    if not contracts:
        return

    # 3. Find a liquid contract to test (e.g. roughly near ATM)
    # Since we don't know the spot price of that day easily without fetching it,
    # let's just pick a middle contract from the list (usually sorted by strike).
    if len(contracts) > 0:
        # Pick middle one
        target_contract = contracts[len(contracts) // 2]
        # Or specifically try to find a CE
        ce_contracts = [c for c in contracts if c.get('instrument_type') == 'CE']
        if ce_contracts:
            target_contract = ce_contracts[len(ce_contracts) // 2]
            
        get_historical_candles(target_contract, expiry_date, token)
    else:
        print("No contracts found to test candles.")

if __name__ == "__main__":
    main()
