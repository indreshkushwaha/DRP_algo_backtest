"""Single source for Upstox access token: token_config.py (updated from frontend or edited manually)."""
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BACKEND_DIR.parent
_TOKEN_PATH = _BACKEND_DIR / "token_config.py"
_LEGACY_TOKEN_PATH = _REPO_ROOT / "token_config.py"


def _ensure_token_config() -> None:
    if _TOKEN_PATH.exists():
        return
    if _LEGACY_TOKEN_PATH.exists():
        _TOKEN_PATH.write_text(_LEGACY_TOKEN_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        _TOKEN_PATH.write_text(
            "# Upstox access token - can be updated from the frontend via API.\n"
            'UPSTOX_ACCESS_TOKEN = ""\n',
            encoding="utf-8",
        )


_ensure_token_config()

from . import token_config  # noqa: E402


def get_access_token() -> str:
    """Read UPSTOX_ACCESS_TOKEN from token_config.py only."""
    try:
        t = (getattr(token_config, "UPSTOX_ACCESS_TOKEN", None) or "").strip()
    except Exception:
        t = ""
    return t


def require_access_token() -> str:
    """Return token or exit with error (for CLI scripts)."""
    t = get_access_token()
    if not t or t == "your_access_token_here":
        print("ERROR: Set UPSTOX_ACCESS_TOKEN in backend/token_config.py (or save via frontend Settings).")
        raise SystemExit(1)
    return t
