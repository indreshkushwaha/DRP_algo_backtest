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

    for leg in instruments:
        instrument_key = leg["instrument_key"]
        side = leg["side"]
        lot_size = leg["lot_size"]

        # Fetch candle data
        df = fetch_1min_data(
            instrument_key,
            from_date=entry_dt.date(),
            to_date=expiry_dt.date()
        )

        # Filter between entry and expiry
        df = df[(df.index >= entry_dt) & (df.index <= expiry_dt)]

        if df.empty:
            raise Exception(f"No data in selected range for {instrument_key}")

        entry_price = df.iloc[0]["close"]

        # Calculate PnL per minute
        if side.upper() == "SELL":
            df[f"pnl_{instrument_key}"] = (
                (entry_price - df["close"]) * lot_size
            )
        else:  # BUY
            df[f"pnl_{instrument_key}"] = (
                (df["close"] - entry_price) * lot_size
            )

        leg_df = df[[f"pnl_{instrument_key}"]]

        if combined_df is None:
            combined_df = leg_df
        else:
            combined_df = combined_df.join(leg_df, how="outer")

    # Fill missing timestamps
    combined_df.fillna(method="ffill", inplace=True)

    # Total PnL column
    pnl_columns = [col for col in combined_df.columns if "pnl_" in col]
    combined_df["total_pnl"] = combined_df[pnl_columns].sum(axis=1)

    return combined_df
