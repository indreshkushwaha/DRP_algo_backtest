instruments = [
    {"instrument_key": "NSE_FO|12345", "side": "SELL", "lot_size": 10},
    {"instrument_key": "NSE_FO|67890", "side": "SELL", "lot_size": 10},
    {"instrument_key": "NSE_FO|54321", "side": "BUY", "lot_size": 10},
    {"instrument_key": "NSE_FO|98765", "side": "BUY", "lot_size": 10},
]

result_df = run_weekly_backtest(
    instruments=instruments,
    entry_datetime="2024-01-01 14:50:00",
    expiry_datetime="2024-01-04 15:30:00"
)

print(result_df.tail())
