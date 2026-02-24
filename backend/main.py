"""
FastAPI backend for backtest config and results.
Run from repo root: uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""
import importlib
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Ensure repo root is on path so we can import find_and_backtest and main
REPO_ROOT = Path(__file__).resolve().parent.parent
TOKEN_CONFIG_PATH = REPO_ROOT / "token_config.py"
RELOAD_TRIGGER_PATH = REPO_ROOT / "backend" / "reload_trigger.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Create token_config.py if missing so import works
if not TOKEN_CONFIG_PATH.exists():
    TOKEN_CONFIG_PATH.write_text(
        '# Upstox access token - can be updated from the frontend via API.\nUPSTOX_ACCESS_TOKEN = ""\n',
        encoding="utf-8",
    )
# Load token_config so we can read/write and reload it
try:
    import token_config
except Exception:
    token_config = None

app = FastAPI(title="Upstox Backtest API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


def _read_token() -> str:
    """Read token from token_config.py only."""
    if token_config is not None and hasattr(token_config, "UPSTOX_ACCESS_TOKEN"):
        return (token_config.UPSTOX_ACCESS_TOKEN or "").strip()
    return ""


def _is_dev() -> bool:
    """True when running in development (local with --reload). On server, set ENV=production to skip reload trigger."""
    return os.getenv("ENV", "").lower() != "production"


def _trigger_reload() -> None:
    """Touch reload_trigger.py so uvicorn --reload restarts the app (dev only; no --reload on server)."""
    if not _is_dev():
        return
    try:
        RELOAD_TRIGGER_PATH.write_text(
            f"# Auto-updated when token is saved from frontend to trigger uvicorn --reload (do not edit)\nRELOAD_TS = {int(time.time())}\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _write_token(token: str) -> None:
    escaped = repr(token)
    content = f"# Upstox access token - can be updated from the frontend via API.\n# Do not commit this file with a real token (see .gitignore).\nUPSTOX_ACCESS_TOKEN = {escaped}\n"
    TOKEN_CONFIG_PATH.write_text(content, encoding="utf-8")
    if token_config is not None:
        importlib.reload(token_config)
    _trigger_reload()


class TokenUpdate(BaseModel):
    access_token: str = Field(..., description="Upstox API access token")


class BacktestConfig(BaseModel):
    entry_datetime: str = "2025-07-25 14:50:00"
    target_premium: float = 50.0
    expiry_date: str = "2025-07-29"
    underlying_key: str = "BSE_INDEX|SENSEX"
    option_type: str = "CE"
    strike_gap: int = 100
    tolerance: float = 5.0
    hedge_difference: int | None = 300
    square_off_when_short_below: float | None = 145.0
    short_pair: bool = True
    phase2_trigger_premium: float | None = 68.0
    phase2_target_reentry: float = 50.0
    phase2_strike_range: int = 15
    phase3_trigger_premium: float | None = 98.0
    phase3_target_reentry: float = 50.0
    phase4_trigger_premium: float | None = 115.0
    phase4_target_reentry: float = 50.0
    stoploss_amount: float | None = 5000.0
    margin: float | None = None
    profit_pct: float | None = None
    lot_size: int | None = None


@app.get("/api/config/token")
def get_token():
    """Return current Upstox access token (for editing in frontend)."""
    return {"access_token": _read_token()}


@app.put("/api/config/token")
def put_token(body: TokenUpdate):
    """Save Upstox access token to token_config.py."""
    _write_token(body.access_token.strip())
    return {"ok": True}


def _compute_summary(result_df):
    """Build summary dict from result DataFrame (must have timestamp index and total_pnl column)."""
    if "total_pnl" not in result_df.columns or result_df.empty:
        return {}
    pnl = result_df["total_pnl"]
    # Max drawdown = when PnL is minimum (worst point)
    min_pnl = pnl.min()
    min_pnl_idx = pnl.idxmin()
    # Max profit = when PnL is maximum (best point)
    max_profit = pnl.max()
    max_profit_idx = pnl.idxmax()
    index = result_df.index
    start_ts = index[0]
    end_ts = index[-1]

    def _ts_str(ts):
        if hasattr(ts, "isoformat"):
            return ts.isoformat()
        return str(ts)

    return {
        "max_drawdown_amount": round(float(min_pnl), 2),
        "max_drawdown_datetime": _ts_str(min_pnl_idx),
        "max_profit_amount": round(float(max_profit), 2),
        "max_profit_datetime": _ts_str(max_profit_idx),
        "final_pnl": round(float(pnl.iloc[-1]), 2),
        "start_datetime": _ts_str(start_ts),
        "end_datetime": _ts_str(end_ts),
        "num_bars": int(len(result_df)),
    }


@app.get("/api/expiries")
def get_expiries_list(
    instrument_key: str = Query(..., description="Underlying key, e.g. BSE_INDEX|SENSEX"),
    from_date: str | None = Query(None, description="Filter expiries on or after (YYYY-MM-DD)"),
    to_date: str | None = Query(None, description="Filter expiries on or before (YYYY-MM-DD)"),
):
    """Return expiry dates for the underlying. API returns only past expiries (~6 months)."""
    from get_instrument import get_expiries as fetch_expiries
    token = _read_token()
    if not token:
        return {"expiries": [], "error": "No access token"}
    all_expiries, err = fetch_expiries(instrument_key, token)
    if err:
        return {"expiries": [], "error": err}
    if not all_expiries:
        return {"expiries": [], "error": "No expiries returned for this instrument"}
    if from_date is None and to_date is None:
        return {"expiries": sorted(all_expiries)}
    filtered = []
    for d in all_expiries:
        if from_date and d < from_date:
            continue
        if to_date and d > to_date:
            continue
        filtered.append(d)
    if filtered:
        return {"expiries": sorted(filtered)}
    return {
        "expiries": sorted(all_expiries),
        "range_matched": False,
        "message": "No expiries in selected range. API returns only past expiries. Showing all available.",
    }


@app.get("/api/config/defaults")
def get_defaults():
    """Return default backtest config for form prefilling."""
    return BacktestConfig().model_dump()


@app.post("/api/backtest")
def run_backtest(config: BacktestConfig):
    """Run backtest with given config; return result table as JSON."""
    import find_and_backtest
    try:
        result_df = find_and_backtest.run(
            entry_datetime=config.entry_datetime,
            target_premium=config.target_premium,
            expiry_date=config.expiry_date,
            underlying_key=config.underlying_key,
            option_type=config.option_type,
            strike_gap=config.strike_gap,
            tolerance=config.tolerance,
            hedge_difference=config.hedge_difference,
            square_off_short_below=config.square_off_when_short_below,
            output_excel=None,
            short_pair=config.short_pair,
            phase2_trigger_premium=config.phase2_trigger_premium,
            phase2_target_reentry=config.phase2_target_reentry,
            phase2_strike_range=config.phase2_strike_range,
            phase3_trigger_premium=config.phase3_trigger_premium,
            phase3_target_reentry=config.phase3_target_reentry,
            phase4_trigger_premium=config.phase4_trigger_premium,
            phase4_target_reentry=config.phase4_target_reentry,
            stoploss_amount=config.stoploss_amount,
            margin=config.margin,
            profit_pct=config.profit_pct,
            lot_size=config.lot_size,
        )
    except SystemExit as e:
        raise HTTPException(status_code=400, detail="Backtest failed: check token and config.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backtest error: {str(e)}")
    if result_df is None:
        raise HTTPException(status_code=400, detail="Backtest returned no data.")

    # Compute summary from total_pnl (before reset_index)
    summary = _compute_summary(result_df)

    # Convert DataFrame to JSON-friendly structure
    result_df = result_df.reset_index()
    result_df["timestamp"] = result_df["timestamp"].astype(str)
    columns = list(result_df.columns)
    data = result_df.to_dict(orient="records")
    # Ensure JSON-serializable and round numerics to 2 decimal places
    for row in data:
        for k, v in row.items():
            if hasattr(v, "item"):
                v = v.item()
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                row[k] = round(float(v), 2)
            elif hasattr(v, "isoformat"):
                row[k] = str(v)
            else:
                row[k] = v
    return {"data": data, "columns": columns, "summary": summary}
