"""
FastAPI backend for weekly backtest.
Exposes run_weekly_backtest from main.py as POST /api/backtest.
"""
import os
from typing import Any, Literal

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

from main import run_weekly_backtest
from backtest_date_range import backtest_date_range

app = FastAPI(title="Weekly Backtest API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class InstrumentItem(BaseModel):
    instrument_key: str
    side: Literal["SELL", "BUY"]
    lot_size: int = Field(..., gt=0)


class BacktestRequest(BaseModel):
    instruments: list[InstrumentItem]
    entry_datetime: str
    expiry_datetime: str
    square_off_short_below: float | None = None


class BacktestDateRangeRequest(BaseModel):
    start_date: str
    end_date: str
    expiry_weekday: int = Field(..., ge=0, le=6)
    entry_days_before_expiry: int = Field(..., ge=0)
    entry_time: str = "14:50:00"
    target_premium: float = Field(..., gt=0)
    underlying_key: str
    option_type: Literal["CE", "PE"] = "CE"
    strike_gap: int = 100
    tolerance: float = 50.0
    hedge_difference: int | None = None
    square_off_short_below: float | None = None
    short_pair: bool = False
    phase2_trigger_premium: float | None = None
    phase2_target_reentry: float = 300.0
    phase2_strike_range: int = 15
    phase3_trigger_premium: float | None = None
    phase3_target_reentry: float = 55.0
    phase4_trigger_premium: float | None = None
    phase4_target_reentry: float = 60.0
    stoploss_amount: float | None = None
    delay_between_expiries_seconds: float = 30.0


def dataframe_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert DataFrame to JSON-serializable records (NaT/NaN -> null, timestamps -> ISO string)."""
    df = df.reset_index()
    if "index" in df.columns and "timestamp" not in df.columns:
        df = df.rename(columns={"index": "timestamp"})
    records = df.to_dict(orient="records")
    out = []
    for r in records:
        cleaned = {}
        for k, v in r.items():
            if pd.isna(v):
                cleaned[k] = None
            elif hasattr(v, "isoformat"):
                cleaned[k] = v.isoformat()
            else:
                cleaned[k] = v
        out.append(cleaned)
    return out


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/backtest")
def backtest(req: BacktestRequest):
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token or token == "your_access_token_here":
        raise HTTPException(
            status_code=503,
            detail="UPSTOX_ACCESS_TOKEN not set or invalid in .env",
        )

    instruments = [
        {"instrument_key": i.instrument_key, "side": i.side, "lot_size": i.lot_size}
        for i in req.instruments
    ]
    if not instruments:
        raise HTTPException(status_code=400, detail="At least one instrument required")
    try:
        result_df = run_weekly_backtest(
            instruments=instruments,
            entry_datetime=req.entry_datetime,
            expiry_datetime=req.expiry_datetime,
            square_off_short_below=req.square_off_short_below,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if result_df is None or result_df.empty:
        raise HTTPException(
            status_code=422,
            detail="No data found for any leg; check instrument keys and date range",
        )
    data = dataframe_to_records(result_df)
    final_pnl = None
    if "total_pnl" in result_df.columns:
        final_pnl = float(result_df["total_pnl"].iloc[-1])
    summary = {"final_pnl": final_pnl, "row_count": len(data)}
    return {"data": data, "summary": summary}


def _build_date_range_summary(combined: pd.DataFrame) -> dict[str, Any]:
    """Build per_expiry and combined_pnl from combined DataFrame (has expiry and total_pnl)."""
    per_expiry: list[dict[str, Any]] = []
    combined_pnl = None
    if "total_pnl" in combined.columns and "expiry" in combined.columns:
        for expiry in sorted(combined["expiry"].unique()):
            subset = combined[combined["expiry"] == expiry]
            final_pnl = float(subset["total_pnl"].iloc[-1])
            per_expiry.append({"expiry": expiry, "final_total_pnl": final_pnl})
        combined_pnl = float(combined.groupby("expiry")["total_pnl"].last().sum())
    return {"per_expiry": per_expiry, "combined_pnl": combined_pnl}


@app.post("/api/backtest/date-range")
def backtest_date_range_endpoint(req: BacktestDateRangeRequest):
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token or token == "your_access_token_here":
        raise HTTPException(
            status_code=503,
            detail="UPSTOX_ACCESS_TOKEN not set or invalid in .env",
        )
    try:
        combined = backtest_date_range(
            start_date=req.start_date,
            end_date=req.end_date,
            expiry_weekday=req.expiry_weekday,
            entry_days_before_expiry=req.entry_days_before_expiry,
            entry_time=req.entry_time,
            output_excel=None,
            target_premium=req.target_premium,
            underlying_key=req.underlying_key,
            option_type=req.option_type,
            strike_gap=req.strike_gap,
            tolerance=req.tolerance,
            hedge_difference=req.hedge_difference,
            square_off_short_below=req.square_off_short_below,
            short_pair=req.short_pair,
            phase2_trigger_premium=req.phase2_trigger_premium,
            phase2_target_reentry=req.phase2_target_reentry,
            phase2_strike_range=req.phase2_strike_range,
            phase3_trigger_premium=req.phase3_trigger_premium,
            phase3_target_reentry=req.phase3_target_reentry,
            phase4_trigger_premium=req.phase4_trigger_premium,
            phase4_target_reentry=req.phase4_target_reentry,
            stoploss_amount=req.stoploss_amount,
            delay_between_expiries_seconds=req.delay_between_expiries_seconds,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if combined is None or combined.empty:
        raise HTTPException(
            status_code=422,
            detail="No backtest data collected for any expiry in the date range",
        )
    data = dataframe_to_records(combined)
    summary = _build_date_range_summary(combined)
    return {
        "data": data,
        "summary": summary,
        "row_count": len(data),
    }
