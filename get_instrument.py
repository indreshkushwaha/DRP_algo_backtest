import requests
import pandas as pd
import os

from get_token import get_access_token

BASE_URL = "https://api.upstox.com/v2"
ACCESS_TOKEN = get_access_token()


def get_expiries(underlying_key: str, access_token: str | None = None) -> tuple[list[str], str | None]:
    """
    Fetch all expiry dates for an underlying from Upstox expired-instruments API.
    Returns (list of YYYY-MM-DD strings, error_message or None).
    Uses access_token if provided, else env. API returns only past/historical expiries (up to ~6 months).
    """
    token = (access_token or ACCESS_TOKEN).strip()
    if not token:
        return [], "No access token"
    url = f"{BASE_URL}/expired-instruments/expiries"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    params = {"instrument_key": underlying_key}
    try:
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
    except Exception as e:
        return [], str(e)
    if response.status_code != 200:
        err = data.get("error") or data.get("message") or response.text or f"HTTP {response.status_code}"
        return [], err
    if data.get("status") != "success" or "data" not in data:
        return [], data.get("error") or data.get("message") or "Invalid response"
    raw = data["data"]
    return (list(raw) if isinstance(raw, list) else []), None


def get_expired_option_contracts(underlying_key, expiry_date, access_token=None):
    """
    Fetch all expired option contracts for a given underlying and expiry date.
    Uses access_token if provided, otherwise current token from get_access_token().
    """
    # #region agent log
    token = (access_token or get_access_token()).strip()
    try:
        with open("/media/indresh/Common_Storage/Devroad/upstox_algo/.cursor/debug.log", "a") as f:
            f.write('{"id":"get_instrument_token","timestamp":' + str(int(__import__("time").time() * 1000)) + ',"location":"get_instrument.py:get_expired_option_contracts","message":"Token used for option contracts","data":{"token_source":"passed" if access_token else "get_access_token","prefix":"' + (token[:8] if token else "") + '"},"hypothesisId":"H1"}\n')
    except Exception:
        pass
    # #endregion

    url = f"{BASE_URL}/expired-instruments/option/contract"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    params = {
        "instrument_key": underlying_key,
        "expiry_date": expiry_date
    }

    response = requests.get(url, headers=headers, params=params)
    data = response.json()

    if "data" not in data:
        print(f"Error: {response.status_code} - {response.text}")
        raise Exception("Invalid response from Upstox API")

    contracts = data["data"]

    if not contracts:
        raise Exception("No contracts found for given expiry")

    df = pd.DataFrame(contracts)

    # Keep only required columns
    df = df[[
        "instrument_key",
        "strike_price",
        "instrument_type",
        "lot_size",
        "expiry"
    ]]

    # Ensure correct types
    df["strike_price"] = df["strike_price"].astype(float)
    df["lot_size"] = df["lot_size"].astype(int)

    return df


# ==============================
# Fetch Data (run only when executed as script)
# ==============================
if __name__ == "__main__":
    contracts_df = get_expired_option_contracts(
        underlying_key="BSE_INDEX|SENSEX",
        expiry_date="2025-07-29"
    )

    print(contracts_df)

    # Save to Excel
    output_file = "sensex_expired_options_2025_07_29.xlsx"
    contracts_df.to_excel(output_file, index=False)

    print(f"Data saved successfully to: {output_file}")
