from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TypedDict

from api.revolut_balances import get_balances
from api.revolut_order_book import get_order_book
from utils.logger import setup_logger
from utils.state_paths import resolve_state_dir
from utils.state_io import read_json_file, write_json_file

logger = setup_logger("revolut_account_sync")

STATE_DIR = resolve_state_dir(Path(__file__).resolve().parent.parent / "state")
ACCOUNT_SNAPSHOT_PATH = STATE_DIR / "revolut_account_snapshot.json"
USD_LIKE_ASSETS = {"USD", "USDT", "USDC", "DAI", "EURC"}
_MID_PRICE_CACHE: dict[str, tuple[float, float]] = {}


class _QuoteCacheStats(TypedDict):
    hits: int
    misses: int
    expired: int
    evicted_stale: int
    evicted_overflow: int
    writes: int
    cleanup_runs: int


_QUOTE_CACHE_STATS: _QuoteCacheStats = {
    "hits": 0,
    "misses": 0,
    "expired": 0,
    "evicted_stale": 0,
    "evicted_overflow": 0,
    "writes": 0,
    "cleanup_runs": 0,
}


def _cache_ttl_seconds() -> float:
    raw = os.getenv("REVBOT_ACCOUNT_QUOTE_CACHE_TTL_SECONDS", "180").strip()
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        parsed = 180.0
    return max(parsed, 1.0)


def _cache_entry_limit() -> int:
    raw = os.getenv("REVBOT_ACCOUNT_QUOTE_CACHE_MAX_ENTRIES", "256").strip()
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = 256
    return max(parsed, 16)


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _best_asset_label(raw: dict) -> str:
    for key in ("asset", "currency", "ccy", "symbol", "code", "aid", "id"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return "UNKNOWN"


def _extract_balance_rows(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        return []

    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        nested = data.get("balances")
        if isinstance(nested, list):
            return [row for row in nested if isinstance(row, dict)]
    balances = payload.get("balances")
    if isinstance(balances, list):
        return [row for row in balances if isinstance(row, dict)]
    return []


def _cleanup_quote_cache(*, now_epoch: float, ttl_seconds: float) -> None:
    _QUOTE_CACHE_STATS["cleanup_runs"] += 1
    stale_keys = [
        key for key, (_price, cached_at) in _MID_PRICE_CACHE.items()
        if (now_epoch - float(cached_at)) > ttl_seconds
    ]
    for key in stale_keys:
        _MID_PRICE_CACHE.pop(key, None)
    if stale_keys:
        _QUOTE_CACHE_STATS["evicted_stale"] += len(stale_keys)
        _QUOTE_CACHE_STATS["expired"] += len(stale_keys)

    limit = _cache_entry_limit()
    overflow = max(0, len(_MID_PRICE_CACHE) - limit)
    if overflow <= 0:
        return
    oldest = sorted(_MID_PRICE_CACHE.items(), key=lambda item: float(item[1][1]))
    for key, _row in oldest[:overflow]:
        _MID_PRICE_CACHE.pop(key, None)
    _QUOTE_CACHE_STATS["evicted_overflow"] += overflow


def quote_cache_telemetry() -> dict:
    return {
        "cache_size": len(_MID_PRICE_CACHE),
        "cache_ttl_seconds": _cache_ttl_seconds(),
        "cache_max_entries": _cache_entry_limit(),
        **_QUOTE_CACHE_STATS,
    }


def _estimate_symbol_mid_price(symbol: str) -> float | None:
    symbol_key = str(symbol or "").strip().upper()
    if not symbol_key:
        return None

    now = time.time()
    ttl_seconds = _cache_ttl_seconds()
    _cleanup_quote_cache(now_epoch=now, ttl_seconds=ttl_seconds)
    cached = _MID_PRICE_CACHE.get(symbol_key)
    if cached is not None:
        price, cached_at = cached
        if (now - cached_at) <= ttl_seconds:
            _QUOTE_CACHE_STATS["hits"] += 1
            return float(price)
        _MID_PRICE_CACHE.pop(symbol_key, None)
        _QUOTE_CACHE_STATS["expired"] += 1

    _QUOTE_CACHE_STATS["misses"] += 1
    try:
        payload = get_order_book(symbol_key)
    except Exception:
        return None

    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    asks = data.get("asks")
    bids = data.get("bids")
    if not isinstance(asks, list) or not isinstance(bids, list):
        return None

    best_ask = None
    for row in asks:
        if not isinstance(row, dict):
            continue
        price = _to_float(row.get("p"), default=0.0)
        if price <= 0:
            continue
        best_ask = price if best_ask is None else min(best_ask, price)

    best_bid = None
    for row in bids:
        if not isinstance(row, dict):
            continue
        price = _to_float(row.get("p"), default=0.0)
        if price <= 0:
            continue
        best_bid = price if best_bid is None else max(best_bid, price)

    if best_ask is None or best_bid is None:
        return None
    if best_bid > best_ask:
        return None
    mid = (best_ask + best_bid) / 2.0
    if mid > 0:
        _MID_PRICE_CACHE[symbol_key] = (float(mid), now)
        _QUOTE_CACHE_STATS["writes"] += 1
        _cleanup_quote_cache(now_epoch=now, ttl_seconds=ttl_seconds)
    return mid


def _estimate_quote_value(asset: str, total: float) -> tuple[float | None, str | None]:
    if total <= 0:
        return 0.0, "zero_balance"
    if asset in USD_LIKE_ASSETS:
        return total, "usd_like"

    symbol = f"{asset}-USD"
    mid = _estimate_symbol_mid_price(symbol)
    if mid is None:
        return None, "price_unavailable"
    return total * mid, "mid_price"


def _build_snapshot_from_payload(payload: dict) -> dict:
    rows = _extract_balance_rows(payload)
    parsed = []
    total_estimated_quote_value = 0.0
    estimated_quote_value_available = True

    for row in rows:
        asset = _best_asset_label(row)
        available = _to_float(
            row.get("available", row.get("free", row.get("balance", row.get("amount", 0.0))))
        )
        locked = _to_float(
            row.get("locked", row.get("hold", row.get("frozen", row.get("in_orders", 0.0))))
        )
        total = max(available, 0.0) + max(locked, 0.0)
        if total <= 0:
            continue

        estimated_quote_value, value_source = _estimate_quote_value(asset, total)
        if estimated_quote_value is None:
            estimated_quote_value_available = False
        else:
            total_estimated_quote_value += estimated_quote_value

        parsed.append(
            {
                "asset": asset,
                "available": round(max(available, 0.0), 12),
                "locked": round(max(locked, 0.0), 12),
                "total": round(total, 12),
                "estimated_quote_value": (
                    None if estimated_quote_value is None else round(float(estimated_quote_value), 6)
                ),
                "estimated_quote_value_source": value_source,
            }
        )

    parsed.sort(key=lambda row: row["asset"])
    return {
        "last_sync_time": time.time(),
        "sync_status": "ok",
        "sync_error": None,
        "assets": parsed,
        "asset_count": len(parsed),
        "estimated_total_quote_value": round(total_estimated_quote_value, 6),
        "estimated_quote_value_complete": bool(estimated_quote_value_available),
        "quote_cache": quote_cache_telemetry(),
        "source": "revolut_x",
    }


def sync_account_snapshot() -> dict:
    try:
        payload = get_balances()
        snapshot = _build_snapshot_from_payload(payload)
    except Exception as exc:
        logger.exception(f"Revolut account sync failed: {exc}")
        previous = read_account_snapshot(default={})
        previous_assets = previous.get("assets") if isinstance(previous, dict) else None
        fallback_assets = previous_assets if isinstance(previous_assets, list) else []
        fallback_total_value = _to_float(
            previous.get("estimated_total_quote_value"),
            default=0.0,
        ) if isinstance(previous, dict) else 0.0
        fallback_complete = bool(previous.get("estimated_quote_value_complete")) if isinstance(previous, dict) else False
        snapshot = {
            "last_sync_time": time.time(),
            "sync_status": "error",
            "sync_error": str(exc),
            "assets": fallback_assets,
            "asset_count": len(fallback_assets),
            "estimated_total_quote_value": round(fallback_total_value, 6),
            "estimated_quote_value_complete": fallback_complete,
            "fallback_from_last_good_snapshot": bool(fallback_assets),
            "last_success_sync_time": (
                previous.get("last_sync_time") if isinstance(previous, dict) else None
            ),
            "quote_cache": quote_cache_telemetry(),
            "source": "revolut_x",
        }

    write_json_file(ACCOUNT_SNAPSHOT_PATH, snapshot, use_lock=True)
    return snapshot


def read_account_snapshot(default: dict | None = None) -> dict:
    fallback = default if isinstance(default, dict) else {}
    snapshot = read_json_file(ACCOUNT_SNAPSHOT_PATH, default=fallback, strict=False)
    if isinstance(snapshot, dict):
        return snapshot
    return fallback
