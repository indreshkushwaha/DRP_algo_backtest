"""
Upstox API – Rate-limited HTTP helper
======================================
Single shared GET function that:
  1. Enforces a minimum delay between consecutive Upstox API calls.
  2. Retries on HTTP 429 ("Too Many Requests") with exponential back-off.

All modules that talk to Upstox should call `upstox_api.get(...)` instead of
`requests.get(...)` so that every request goes through one throttle.

Configuration (override via environment variables or edit constants below):
  UPSTOX_REQUEST_DELAY   – seconds between requests   (default 0.6)
  UPSTOX_RETRY_429_MAX   – max retries on 429          (default 3)
  UPSTOX_RETRY_BACKOFF   – initial back-off in seconds (default 20)
"""

import os
import time

import requests

# ---------------------------------------------------------------------------
# Configurable constants (can be overridden via env vars)
# 0.6s between requests ≈ 100/min, well under typical 500/min limit.
# Longer backoff on 429 gives the per-minute window time to reset.
# ---------------------------------------------------------------------------
REQUEST_DELAY_SECONDS: float = float(os.getenv("UPSTOX_REQUEST_DELAY", "0.6"))
RETRY_429_MAX: int = int(os.getenv("UPSTOX_RETRY_429_MAX", "3"))
RETRY_429_BACKOFF_BASE: float = float(os.getenv("UPSTOX_RETRY_BACKOFF", "20"))

# ---------------------------------------------------------------------------
# Module-level state: timestamp of last request (shared across all callers)
# ---------------------------------------------------------------------------
_last_request_time: float = 0.0


def get(url: str, *, headers: dict | None = None, timeout: int = 30, **kwargs) -> requests.Response:
    """
    Rate-limited wrapper around ``requests.get``.

    Parameters
    ----------
    url : str
        Full URL to GET.
    headers : dict, optional
        HTTP headers (typically Authorization + Accept).
    timeout : int
        Request timeout in seconds.
    **kwargs
        Any extra keyword arguments forwarded to ``requests.get``
        (e.g. ``params``).

    Returns
    -------
    requests.Response
        The HTTP response object, exactly as ``requests.get`` would return.
        On persistent 429 after all retries, the last 429 response is returned
        so callers can handle it the same way they already handle errors.
    """
    global _last_request_time

    for attempt in range(1 + RETRY_429_MAX):
        # ---- throttle: wait until at least REQUEST_DELAY_SECONDS since last call ----
        elapsed = time.time() - _last_request_time
        if elapsed < REQUEST_DELAY_SECONDS:
            time.sleep(REQUEST_DELAY_SECONDS - elapsed)

        _last_request_time = time.time()
        resp = requests.get(url, headers=headers, timeout=timeout, **kwargs)

        if resp.status_code != 429:
            return resp

        # ---- 429 received – back off and retry ----
        if attempt < RETRY_429_MAX:
            backoff = RETRY_429_BACKOFF_BASE * (2 ** attempt)  # 5, 10, 20 …
            print(
                f"[upstox_api] 429 Too Many Requests – retry {attempt + 1}/{RETRY_429_MAX} "
                f"after {backoff:.0f}s …"
            )
            time.sleep(backoff)
        else:
            print(
                f"[upstox_api] 429 Too Many Requests – all {RETRY_429_MAX} retries exhausted. "
                f"Returning 429 response to caller."
            )

    return resp  # last 429 response
