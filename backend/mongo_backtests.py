"""Optional persistence of backtest results to MongoDB."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from .config import MONGODB_URI

logger = logging.getLogger(__name__)

DB_NAME = "drp_backtest"
COLLECTION_NAME = "backtest_runs"

_client: MongoClient | None = None
_indexes_ensured = False


def _uri_enabled() -> bool:
    return bool((MONGODB_URI or "").strip())


def _collection():
    global _client, _indexes_ensured
    if not _uri_enabled():
        return None
    if _client is None:
        _client = MongoClient((MONGODB_URI or "").strip(), serverSelectionTimeoutMS=8000)
    coll = _client[DB_NAME][COLLECTION_NAME]
    if not _indexes_ensured:
        try:
            coll.create_index([("underlying_key", 1), ("expiry_date", 1)], unique=True)
        except PyMongoError as e:
            logger.warning("MongoDB index ensure failed: %s", e)
        _indexes_ensured = True
    return coll


def save_run(
    underlying_key: str,
    expiry_date: str,
    margin: Any,
    config_dump: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    """Upsert one backtest run. Swallows errors after logging."""
    coll = _collection()
    if coll is None:
        return
    data = payload.get("data") or []
    try:
        doc = {
            "underlying_key": underlying_key,
            "expiry_date": expiry_date,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "deleted": False,
            "deleted_at": None,
            "row_count": len(data) if isinstance(data, list) else 0,
            "data": payload.get("data"),
            "columns": payload.get("columns"),
            "summary": payload.get("summary"),
            "logs": payload.get("logs"),
            "margin": margin,
            "config": config_dump,
        }
        coll.update_one(
            {"underlying_key": underlying_key, "expiry_date": expiry_date},
            {"$set": doc},
            upsert=True,
        )
    except PyMongoError as e:
        logger.warning("MongoDB save_run failed: %s", e, exc_info=True)
    except Exception as e:
        logger.warning("MongoDB save_run failed: %s", e, exc_info=True)


def list_runs_for_underlying(
    underlying_key: str,
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    coll = _collection()
    if coll is None:
        return []
    try:
        out: list[dict[str, Any]] = []
        query: dict[str, Any] = {"underlying_key": underlying_key}
        if not include_deleted:
            query["$or"] = [{"deleted": {"$exists": False}}, {"deleted": False}]
        for doc in coll.find(query, projection={"data": 0, "logs": 0, "config": 0}):
            summary = doc.get("summary") or {}
            fp = summary.get("final_pnl")
            out.append(
                {
                    "expiry_date": doc.get("expiry_date"),
                    "saved_at": doc.get("saved_at"),
                    "final_pnl": fp,
                    "row_count": doc.get("row_count"),
                    "deleted": bool(doc.get("deleted", False)),
                    "deleted_at": doc.get("deleted_at"),
                }
            )
        return out
    except PyMongoError as e:
        logger.warning("MongoDB list_runs_for_underlying failed: %s", e, exc_info=True)
        return []


def get_run(
    underlying_key: str,
    expiry_date: str,
    include_deleted: bool = False,
) -> dict[str, Any] | None:
    coll = _collection()
    if coll is None:
        return None
    try:
        query: dict[str, Any] = {"underlying_key": underlying_key, "expiry_date": expiry_date}
        if not include_deleted:
            query["$or"] = [{"deleted": {"$exists": False}}, {"deleted": False}]
        doc = coll.find_one(query)
        if not doc:
            return None
        doc.pop("_id", None)
        return doc
    except PyMongoError as e:
        logger.warning("MongoDB get_run failed: %s", e, exc_info=True)
        return None


def soft_delete_run(underlying_key: str, expiry_date: str) -> bool:
    """Soft-delete one stored run by setting deleted flags."""
    coll = _collection()
    if coll is None:
        return False
    try:
        result = coll.update_one(
            {
                "underlying_key": underlying_key,
                "expiry_date": expiry_date,
                "$or": [{"deleted": {"$exists": False}}, {"deleted": False}],
            },
            {
                "$set": {
                    "deleted": True,
                    "deleted_at": datetime.now(timezone.utc).isoformat(),
                }
            },
        )
        return bool(result.modified_count)
    except PyMongoError as e:
        logger.warning("MongoDB soft_delete_run failed: %s", e, exc_info=True)
        return False


def serialize_run_for_api(doc: dict[str, Any]) -> dict[str, Any]:
    """Shape stored document for the frontend (aligns with loadSavedRun / hydrate)."""
    return {
        "underlying_key": doc.get("underlying_key"),
        "expiry_date": doc.get("expiry_date"),
        "savedAt": doc.get("saved_at"),
        "data": doc.get("data"),
        "columns": doc.get("columns"),
        "summary": doc.get("summary"),
        "logs": doc.get("logs"),
        "margin": doc.get("margin"),
    }
