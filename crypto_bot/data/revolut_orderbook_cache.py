from __future__ import annotations

import copy
import os
import time
from collections import OrderedDict
from threading import RLock

from api.revolut_order_book import get_order_book
from data.revolut_market_db import insert_orderbook_snapshot


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


ORDERBOOK_CACHE_MAX_SYMBOLS = max(_int_env("REVBOT_ORDERBOOK_CACHE_MAX_SYMBOLS", 300), 10)
ORDERBOOK_CACHE_STALE_SECONDS = max(_int_env("REVBOT_ORDERBOOK_CACHE_STALE_SECONDS", 10), 1)

orderbook_cache: "OrderedDict[str, dict]" = OrderedDict()
_last_snapshot_persist_ts: dict[str, int] = {}
_metrics = {
    "hits": 0,
    "misses": 0,
    "stale_hits": 0,
    "evictions": 0,
    "updates": 0,
}
_cache_lock = RLock()


def _parse_level(level: dict) -> tuple[float, float] | None:
    if not isinstance(level, dict):
        return None
    raw_price = level.get("p", level.get("price"))
    raw_size = level.get("q", level.get("size"))
    try:
        price = float(raw_price)
        size = float(raw_size)
    except (TypeError, ValueError):
        return None
    if price <= 0 or size <= 0:
        return None
    return price, size


def fetch_orderbook_top5(symbol: str) -> dict:
    payload = get_order_book(symbol)
    data = payload.get("data", {}) if isinstance(payload, dict) else {}

    bids = [_parse_level(row) for row in data.get("bids", []) if isinstance(data.get("bids"), list)]
    asks = [_parse_level(row) for row in data.get("asks", []) if isinstance(data.get("asks"), list)]
    bid_levels = [item for item in bids if item is not None]
    ask_levels = [item for item in asks if item is not None]

    bid_levels = sorted(bid_levels, key=lambda item: item[0], reverse=True)[:5]
    ask_levels = sorted(ask_levels, key=lambda item: item[0])[:5]
    if not bid_levels or not ask_levels:
        raise ValueError(f"No valid order book levels available for {symbol}")

    best_bid = bid_levels[0][0]
    best_ask = ask_levels[0][0]
    spread = best_ask - best_bid
    bid_volume_top5 = sum(level[1] for level in bid_levels)
    ask_volume_top5 = sum(level[1] for level in ask_levels)
    denom = bid_volume_top5 + ask_volume_top5
    imbalance = ((bid_volume_top5 - ask_volume_top5) / denom) if denom > 0 else 0.0

    return {
        "ts": int(time.time() * 1000),
        "bids": bid_levels,
        "asks": ask_levels,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "bid_volume_top5": bid_volume_top5,
        "ask_volume_top5": ask_volume_top5,
        "imbalance": imbalance,
        "source": "revolut",
    }


def update_orderbook_cache(
    symbol: str,
    *,
    persist: bool = False,
    persist_every_seconds: int = 30,
    db_path=None,
) -> dict:
    snapshot = fetch_orderbook_top5(symbol)
    with _cache_lock:
        key = str(symbol).strip().upper()
        snapshot["cache_updated_at_ms"] = int(time.time() * 1000)
        orderbook_cache[key] = snapshot
        orderbook_cache.move_to_end(key)
        _metrics["updates"] = int(_metrics.get("updates", 0) or 0) + 1
        while len(orderbook_cache) > int(ORDERBOOK_CACHE_MAX_SYMBOLS):
            orderbook_cache.popitem(last=False)
            _metrics["evictions"] = int(_metrics.get("evictions", 0) or 0) + 1

    if persist:
        last_saved = _last_snapshot_persist_ts.get(symbol, 0)
        now_ms = int(snapshot["ts"])
        if (now_ms - int(last_saved)) >= int(persist_every_seconds) * 1000:
            insert_orderbook_snapshot(symbol=symbol, snapshot=snapshot, db_path=db_path, source="revolut")
            _last_snapshot_persist_ts[symbol] = now_ms

    return snapshot


def get_orderbook_cache(symbol: str, *, stale_after_seconds: int | None = None) -> dict | None:
    now_ms = int(time.time() * 1000)
    stale_after = max(
        int(stale_after_seconds) if stale_after_seconds is not None else int(ORDERBOOK_CACHE_STALE_SECONDS),
        1,
    )
    key = str(symbol).strip().upper()
    with _cache_lock:
        snapshot = orderbook_cache.get(key)
        if snapshot is None:
            _metrics["misses"] = int(_metrics.get("misses", 0) or 0) + 1
            return None
        orderbook_cache.move_to_end(key)
        payload = copy.deepcopy(snapshot)
        age_seconds = max(0.0, (now_ms - int(payload.get("ts", now_ms))) / 1000.0)
        is_stale = age_seconds > float(stale_after)
        payload["cache_age_seconds"] = age_seconds
        payload["stale"] = bool(is_stale)
        _metrics["hits"] = int(_metrics.get("hits", 0) or 0) + 1
        if is_stale:
            _metrics["stale_hits"] = int(_metrics.get("stale_hits", 0) or 0) + 1
        return payload


def get_orderbook_cache_metrics() -> dict:
    with _cache_lock:
        return {
            "size": int(len(orderbook_cache)),
            "max_symbols": int(ORDERBOOK_CACHE_MAX_SYMBOLS),
            "stale_after_seconds": int(ORDERBOOK_CACHE_STALE_SECONDS),
            "hits": int(_metrics.get("hits", 0) or 0),
            "misses": int(_metrics.get("misses", 0) or 0),
            "stale_hits": int(_metrics.get("stale_hits", 0) or 0),
            "evictions": int(_metrics.get("evictions", 0) or 0),
            "updates": int(_metrics.get("updates", 0) or 0),
        }
