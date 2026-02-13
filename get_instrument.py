import requests
import pandas as pd
import os
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.upstox.com/v2"
ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()


def get_expired_option_contracts(underlying_key, expiry_date):
    """
    Fetch all expired option contracts for a given underlying and expiry date.
    """

    url = f"{BASE_URL}/expired-instruments/option/contract"

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
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
