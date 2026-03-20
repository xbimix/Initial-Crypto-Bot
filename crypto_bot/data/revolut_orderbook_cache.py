from __future__ import annotations

import copy
import time

from api.revolut_order_book import get_order_book
from data.revolut_market_db import insert_orderbook_snapshot


orderbook_cache: dict[str, dict] = {}
_last_snapshot_persist_ts: dict[str, int] = {}


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
    orderbook_cache[symbol] = snapshot

    if persist:
        last_saved = _last_snapshot_persist_ts.get(symbol, 0)
        now_ms = int(snapshot["ts"])
        if (now_ms - int(last_saved)) >= int(persist_every_seconds) * 1000:
            insert_orderbook_snapshot(symbol=symbol, snapshot=snapshot, db_path=db_path, source="revolut")
            _last_snapshot_persist_ts[symbol] = now_ms

    return snapshot


def get_orderbook_cache(symbol: str) -> dict | None:
    snapshot = orderbook_cache.get(symbol)
    return copy.deepcopy(snapshot) if snapshot is not None else None

