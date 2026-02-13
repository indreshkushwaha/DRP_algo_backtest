from __future__ import annotations

"""
Upstox API Test Script — Expiring Options
==========================================
Tests whether the Upstox API is correctly retrieving
option data for NIFTY 50 expiring options.

Usage:
    1. Paste your access token in `.env`
    2. pip install -r requirements.txt
    3. python test_upstox_options.py
"""

import os
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv
from tabulate import tabulate

# ── Configuration ────────────────────────────────────────────────────────────
BASE_URL = "https://api.upstox.com/v2"
INSTRUMENT_KEY = "NSE_INDEX|Nifty 50"          # Nifty 50 index
NUM_STRIKES_AROUND_ATM = 10                     # Show ±10 strikes around ATM


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_access_token() -> str:
    """Load access token from .env file."""
    load_dotenv()
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token or token == "your_access_token_here":
        print("❌ ERROR: Please set your UPSTOX_ACCESS_TOKEN in the .env file.")
        print("   Open .env and replace 'your_access_token_here' with your actual token.")
        sys.exit(1)
    return token


def make_request(endpoint: str, params: dict, token: str) -> dict:
    """Make an authenticated GET request to the Upstox API."""
    url = f"{BASE_URL}{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code
        if status == 401:
            print("❌ ERROR: Unauthorized — your access token is invalid or expired.")
            print("   Upstox tokens expire at 3:30 AM IST daily. Generate a new one.")
        elif status == 400:
            print(f"❌ ERROR: Bad request — {e.response.text}")
        else:
            print(f"❌ ERROR: HTTP {status} — {e.response.text}")
        return {}
    except requests.exceptions.ConnectionError:
        print("❌ ERROR: Could not connect to Upstox API. Check your internet connection.")
        return {}
    except requests.exceptions.Timeout:
        print("❌ ERROR: Request timed out.")
        return {}


def print_banner(title: str):
    """Print a formatted section banner."""
    width = 60
    print("\n" + "═" * width)
    print(f"  {title}")
    print("═" * width)


# ── Test 1: Fetch Option Contracts & Expiry Dates ───────────────────────────

def test_option_contracts(token: str) -> list[str]:
    """
    Fetch all option contracts for NIFTY 50 and extract unique expiry dates.
    Returns sorted list of expiry date strings.
    """
    print_banner("TEST 1 — Fetch Option Contracts (Expiry Dates)")

    data = make_request(
        "/option/contract",
        {"instrument_key": INSTRUMENT_KEY},
        token,
    )

    if not data or data.get("status") != "success":
        print("❌ FAILED: Could not fetch option contracts.")
        return []

    contracts = data.get("data", [])
    if not contracts:
        print("❌ FAILED: API returned empty contract list.")
        return []

    # Extract unique expiry dates and sort them
    expiries = sorted(set(c["expiry"] for c in contracts if c.get("expiry")))

    print(f"✅ PASSED: Retrieved {len(contracts)} option contracts.")
    print(f"   Found {len(expiries)} unique expiry dates:\n")

    # Separate into upcoming and past
    today = datetime.now().strftime("%Y-%m-%d")
    upcoming = [e for e in expiries if e >= today]
    past = [e for e in expiries if e < today]

    if upcoming:
        # Show upcoming expiries in a nice table
        table_data = []
        for i, exp in enumerate(upcoming[:12], 1):  # Show first 12
            exp_date = datetime.strptime(exp, "%Y-%m-%d")
            day_name = exp_date.strftime("%A")
            days_left = (exp_date - datetime.now()).days
            label = "⬅ NEAREST" if i == 1 else ""
            table_data.append([i, exp, day_name, f"{days_left}d", label])

        print(tabulate(
            table_data,
            headers=["#", "Expiry Date", "Day", "Days Left", ""],
            tablefmt="rounded_outline",
        ))

        if len(upcoming) > 12:
            print(f"   ... and {len(upcoming) - 12} more expiry dates")
    else:
        print("   ⚠ No upcoming expiry dates found (market may be closed).")

    return upcoming


# ── Test 2: Fetch Option Chain for Nearest Expiry ────────────────────────────

def test_option_chain(token: str, expiry_date: str) -> list[dict]:
    """
    Fetch the put/call option chain for the given expiry date.
    Returns list of option chain entries.
    """
    print_banner(f"TEST 2 — Fetch Option Chain (Expiry: {expiry_date})")

    data = make_request(
        "/option/chain",
        {"instrument_key": INSTRUMENT_KEY, "expiry_date": expiry_date},
        token,
    )

    if not data or data.get("status") != "success":
        print("❌ FAILED: Could not fetch option chain.")
        return []

    chain = data.get("data", [])
    if not chain:
        print("❌ FAILED: API returned empty option chain.")
        return []

    # Get spot price from the first entry
    spot_price = chain[0].get("underlying_spot_price", 0)

    print(f"✅ PASSED: Retrieved option chain with {len(chain)} strike prices.")
    print(f"   Underlying Spot Price: ₹{spot_price:,.2f}")
    print(f"   Expiry Date: {expiry_date}")

    return chain


# ── Test 3: Display Filtered Option Chain Table ──────────────────────────────

def display_option_chain_table(chain: list[dict]):
    """
    Display a clean, filtered table of the option chain
    showing strikes around the ATM price.
    """
    print_banner("TEST 3 — Option Chain Summary (ATM ± 10 Strikes)")

    if not chain:
        print("❌ FAILED: No data to display.")
        return

    spot_price = chain[0].get("underlying_spot_price", 0)

    # Sort by strike price
    chain_sorted = sorted(chain, key=lambda x: x.get("strike_price", 0))

    # Find ATM strike (closest to spot price)
    atm_idx = min(
        range(len(chain_sorted)),
        key=lambda i: abs(chain_sorted[i].get("strike_price", 0) - spot_price),
    )

    # Filter: ATM ± NUM_STRIKES_AROUND_ATM
    start = max(0, atm_idx - NUM_STRIKES_AROUND_ATM)
    end = min(len(chain_sorted), atm_idx + NUM_STRIKES_AROUND_ATM + 1)
    filtered = chain_sorted[start:end]

    # Build table
    table_data = []
    for entry in filtered:
        strike = entry.get("strike_price", 0)
        is_atm = "→" if abs(strike - spot_price) == min(
            abs(s.get("strike_price", 0) - spot_price) for s in filtered
        ) else ""

        call = entry.get("call_options", {})
        put = entry.get("put_options", {})
        call_md = call.get("market_data", {})
        put_md = put.get("market_data", {})
        call_greeks = call.get("option_greeks", {})
        put_greeks = put.get("option_greeks", {})

        table_data.append([
            # CE side
            f"{call_md.get('oi', 0):,}",
            f"{call_md.get('volume', 0):,}",
            f"{call_greeks.get('iv', 0):.1f}",
            f"{call_greeks.get('delta', 0):.3f}",
            f"₹{call_md.get('ltp', 0):,.2f}",
            # Strike
            f"{is_atm} {strike:,.0f}",
            # PE side
            f"₹{put_md.get('ltp', 0):,.2f}",
            f"{put_greeks.get('delta', 0):.3f}",
            f"{put_greeks.get('iv', 0):.1f}",
            f"{put_md.get('volume', 0):,}",
            f"{put_md.get('oi', 0):,}",
        ])

    headers = [
        "CE OI", "CE Vol", "CE IV", "CE Δ", "CE LTP",
        "Strike",
        "PE LTP", "PE Δ", "PE IV", "PE Vol", "PE OI",
    ]

    print(f"\n   Spot: ₹{spot_price:,.2f}  |  Showing {len(filtered)} strikes\n")
    print(tabulate(table_data, headers=headers, tablefmt="rounded_outline", stralign="right"))
    print(f"\n   → = ATM strike  |  PCR (at ATM) shown above")

    # Summary stats
    total_ce_oi = sum(
        e.get("call_options", {}).get("market_data", {}).get("oi", 0) for e in filtered
    )
    total_pe_oi = sum(
        e.get("put_options", {}).get("market_data", {}).get("oi", 0) for e in filtered
    )
    pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 0

    print(f"\n   📊 Summary (filtered strikes):")
    print(f"      Total CE OI: {total_ce_oi:,}")
    print(f"      Total PE OI: {total_pe_oi:,}")
    print(f"      Put-Call Ratio (PCR): {pcr:.2f}")

    print("\n✅ PASSED: Option chain displayed successfully.")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "╔" + "═" * 58 + "╗")
    print("║   UPSTOX API TEST — Expiring Options (NIFTY 50)         ║")
    print("╚" + "═" * 58 + "╝")
    print(f"   Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")

    # Load token
    token = load_access_token()
    print(f"   Token loaded: {token[:8]}...{token[-4:]}\n")

    # Test 1: Fetch option contracts & expiry dates
    expiries = test_option_contracts(token)
    if not expiries:
        print("\n🛑 Stopping — could not retrieve expiry dates.")
        sys.exit(1)

    # Use the nearest expiry for the next tests
    nearest_expiry = expiries[0]

    # Test 2: Fetch option chain for nearest expiry
    chain = test_option_chain(token, nearest_expiry)
    if not chain:
        print("\n🛑 Stopping — could not retrieve option chain.")
        sys.exit(1)

    # Test 3: Display filtered option chain
    display_option_chain_table(chain)

    # Final verdict
    print("\n" + "╔" + "═" * 58 + "╗")
    print("║   ✅ ALL TESTS PASSED — API is working correctly!       ║")
    print("╚" + "═" * 58 + "╝\n")


if __name__ == "__main__":
    main()
