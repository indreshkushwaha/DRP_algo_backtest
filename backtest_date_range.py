"""
Backtest Over Date Range and Combine Results
=============================================
Takes a date range (start_date, end_date) and all backtest parameters.
Finds all expiries (e.g. weekly Thursdays) within the range.
For each expiry, runs the existing backtest via find_and_backtest.run(),
collects the DataFrames, adds an `expiry` column, concatenates, and
saves to a single Excel file.

Usage:
    Update CONFIGURATION in __main__ block and run:
        python backtest_date_range.py
"""

import time
from datetime import date, datetime, timedelta

import pandas as pd

import find_and_backtest


# ---------------------------------------------------------------------------
# Helper: generate expiry dates within a range
# ---------------------------------------------------------------------------
def get_expiries_in_range(start_date: str, end_date: str, weekday: int) -> list[str]:
    """
    Return sorted list of date strings (YYYY-MM-DD) for all dates whose
    weekday() == `weekday` within [start_date, end_date].
    weekday: 0=Monday, 1=Tuesday, … 3=Thursday, 4=Friday, …
    """
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    expiries: list[str] = []
    current = start
    while current <= end:
        if current.weekday() == weekday:
            expiries.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return expiries


# ---------------------------------------------------------------------------
# Helper: compute entry datetime for a given expiry
# ---------------------------------------------------------------------------
def entry_datetime_for_expiry(expiry_date: str, days_before: int, time_str: str) -> str:
    """
    Compute entry datetime string for an expiry.
    entry_date = expiry_date - timedelta(days=days_before)
    Returns "YYYY-MM-DD HH:MM:SS".
    """
    exp = datetime.strptime(expiry_date, "%Y-%m-%d").date()
    entry_date = exp - timedelta(days=days_before)
    return f"{entry_date} {time_str}"


# ---------------------------------------------------------------------------
# Main function: all parameters are explicit arguments
# ---------------------------------------------------------------------------
def backtest_date_range(
    # ---- Range parameters ----
    start_date: str,
    end_date: str,
    expiry_weekday: int,          # 0=Mon … 3=Thu
    entry_days_before_expiry: int,
    entry_time: str,              # e.g. "14:50:00"
    # ---- Backtest parameters (same as find_and_backtest.run) ----
    target_premium: float,
    underlying_key: str,
    option_type: str = "CE",
    strike_gap: int = 100,
    tolerance: float = 50.0,
    hedge_difference: int | None = None,
    square_off_short_below: float | None = None,
    short_pair: bool = False,
    phase2_trigger_premium: float | None = None,
    phase2_target_reentry: float = 300.0,
    phase2_strike_range: int = 15,
    phase3_trigger_premium: float | None = None,
    phase3_target_reentry: float = 55.0,
    phase4_trigger_premium: float | None = None,
    phase4_target_reentry: float = 60.0,
    stoploss_amount: float | None = None,
    delay_between_expiries_seconds: float = 30.0,  # pause between expiries to avoid 429
    output_excel: str | None = None,  # None = do not write Excel (e.g. when called from API)
) -> "pd.DataFrame | None":
    """
    Run backtests for every expiry in [start_date, end_date] and combine
    results into a single DataFrame / Excel file.

    Returns the combined DataFrame, or None if no expiry produced data.
    """

    # 1. Find all expiry dates in the range
    expiries = get_expiries_in_range(start_date, end_date, expiry_weekday)
    if not expiries:
        print(f"No expiries found between {start_date} and {end_date} for weekday={expiry_weekday}")
        return None

    print(f"Found {len(expiries)} expiries in range: {expiries}")

    # 2. Loop over each expiry and collect results
    all_dfs: list[pd.DataFrame] = []
    skipped_expiries: list[str] = []  # expiries that returned no data (e.g. 429)

    for expiry in expiries:
        entry_dt = entry_datetime_for_expiry(expiry, entry_days_before_expiry, entry_time)
        print(f"\n{'='*70}")
        print(f"Running backtest for expiry={expiry}  entry={entry_dt}")
        print(f"{'='*70}")

        result_df = find_and_backtest.run(
            entry_datetime=entry_dt,
            target_premium=target_premium,
            expiry_date=expiry,
            underlying_key=underlying_key,
            option_type=option_type,
            strike_gap=strike_gap,
            tolerance=tolerance,
            hedge_difference=hedge_difference,
            square_off_short_below=square_off_short_below,
            output_excel=None,          # don't write per-expiry files
            short_pair=short_pair,
            phase2_trigger_premium=phase2_trigger_premium,
            phase2_target_reentry=phase2_target_reentry,
            phase2_strike_range=phase2_strike_range,
            phase3_trigger_premium=phase3_trigger_premium,
            phase3_target_reentry=phase3_target_reentry,
            phase4_trigger_premium=phase4_trigger_premium,
            phase4_target_reentry=phase4_target_reentry,
            stoploss_amount=stoploss_amount,
        )

        if result_df is not None and not result_df.empty:
            result_df["expiry"] = expiry
            all_dfs.append(result_df)
            print(f"Collected {len(result_df)} rows for expiry {expiry}")
        else:
            skipped_expiries.append(expiry)
            print(f"No data returned for expiry {expiry}, skipping.")

        # Pause between expiries to stay under Upstox per-minute rate limit
        if delay_between_expiries_seconds > 0 and expiry != expiries[-1]:
            print(f"Waiting {delay_between_expiries_seconds:.0f}s before next expiry …")
            time.sleep(delay_between_expiries_seconds)

    # 3. Combine and save
    if not all_dfs:
        print("\nNo backtest data collected for any expiry.")
        return None

    combined = pd.concat(all_dfs)
    # Keep order: one block per expiry (do not sort by timestamp globally, which would mix weeks)
    combined = combined.sort_values(by=["expiry"])

    # Build summary: include skipped expiries, then per-expiry final PnL, then combined total
    summary_rows = []
    for exp in skipped_expiries:
        summary_rows.append({"expiry": exp, "final_total_pnl": "No data (skipped)"})
    if "total_pnl" in combined.columns:
        for expiry in sorted(combined["expiry"].unique()):
            subset = combined[combined["expiry"] == expiry]
            final_pnl = subset["total_pnl"].iloc[-1]
            summary_rows.append({"expiry": expiry, "final_total_pnl": final_pnl})
        overall = combined.groupby("expiry")["total_pnl"].last().sum()
        summary_rows.append({"expiry": "Combined", "final_total_pnl": overall})
    summary_df = pd.DataFrame(summary_rows)

    # Write Data sheet with timestamp as a normal column so Excel shows it (index can appear blank)
    data_to_write = combined.reset_index()
    if data_to_write.index.name is None and "timestamp" not in data_to_write.columns:
        data_to_write = data_to_write.rename(columns={"index": "timestamp"})

    if output_excel is not None:
        # Save to Excel: Data = bar data, Summary = per-expiry and combined amount
        with pd.ExcelWriter(output_excel, engine="openpyxl") as writer:
            data_to_write.to_excel(writer, sheet_name="Data", index=False)
            if not summary_df.empty:
                summary_df.to_excel(writer, sheet_name="Summary", index=False)
        print(f"\nCombined results ({len(combined)} rows from {len(all_dfs)} expiries) saved to {output_excel}")

    # Print per-expiry summary
    print("\n--- Per-expiry PnL summary ---")
    for _, row in summary_df.iterrows():
        print(f"  {row['expiry']}: final total_pnl = {row['final_total_pnl']}")

    return combined


# ---------------------------------------------------------------------------
# Script entrypoint: all parameters set here, passed to backtest_date_range
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    backtest_date_range(
        # ---- Range parameters ----
        start_date="2025-08-15",
        end_date="2025-08-31",
        expiry_weekday=1,             # 1 = Tuesday (BSE SENSEX weekly expiry)
        entry_days_before_expiry=4,   # enter 4 days before expiry (Friday before Tuesday)
        entry_time="14:50:00",
        output_excel="backtest_date_range_results.xlsx",
        # ---- Backtest parameters ----
        target_premium=50.0,
        underlying_key="BSE_INDEX|SENSEX",
        option_type="CE",
        strike_gap=100,
        tolerance=5.0,
        hedge_difference=300,
        square_off_short_below=None,
        short_pair=True,
        phase2_trigger_premium=68.0,
        phase2_target_reentry=50.0,
        phase2_strike_range=15,
        phase3_trigger_premium=98.0,
        phase3_target_reentry=45.0,
        phase4_trigger_premium=115.0,
        phase4_target_reentry=65.0,
        stoploss_amount=5000,
        delay_between_expiries_seconds=30.0,  # reduce 429 when running many expiries
    )
