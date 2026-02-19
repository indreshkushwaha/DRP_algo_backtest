"""Single source for Upstox access token: token_config.py (updated from frontend or edited manually)."""
import os


def get_access_token() -> str:
    """Read UPSTOX_ACCESS_TOKEN from token_config.py only."""
    try:
        import token_config
        t = (getattr(token_config, "UPSTOX_ACCESS_TOKEN", None) or "").strip()
    except Exception:
        t = ""
    return t


def require_access_token() -> str:
    """Return token or exit with error (for CLI scripts)."""
    t = get_access_token()
    if not t or t == "your_access_token_here":
        print("ERROR: Set UPSTOX_ACCESS_TOKEN in token_config.py (or save via frontend Settings).")
        raise SystemExit(1)
    return t
