from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from api.revolut_order_book import get_order_book
from api.revolut_trades import get_last_trades


FUTURE_TRADE_TOLERANCE_SECONDS = 5.0


def _epoch_to_seconds(value: float) -> float | None:
    if value <= 0:
        return None
    # Revolut payloads can carry either Unix epoch milliseconds or seconds.
    if value >= 1_000_000_000_000:
        return float(value / 1000.0)
    if value >= 1_000_000_000:
        return float(value)
    return None


def _parse_ts(value: Any) -> float | None:
    if isinstance(value, dict):
        for key in (
            "tdt",
            "pdt",
            "timestamp",
            "time",
            "ts",
            "start",
            "created_date",
            "updated_date",
        ):
            candidate = value.get(key)
            if candidate is not None:
                value = candidate
                break
        else:
            return None
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return _epoch_to_seconds(float(value))
    try:
        raw = str(value).strip()
        if not raw:
            return None
        try:
            return _epoch_to_seconds(float(raw))
        except (TypeError, ValueError):
            pass
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_symbol(symbol: str) -> str:
    raw = str(symbol or "").strip().upper()
    if not raw:
        return ""
    raw = raw.replace("/", "-").replace("_", "-")
    if "-" in raw:
        base, quote = raw.split("-", 1)
        return f"{base.strip().upper()}-{quote.strip().upper()}"
    return raw


def _split_symbol(symbol: str) -> tuple[str, str]:
    base, quote = normalize_symbol(symbol).split("-", 1)
    return base, quote


def _matches_symbol_row(row: dict[str, Any], base: str, quote: str) -> bool:
    pair = normalize_symbol(
        row.get("symbol")
        or row.get("pair")
        or row.get("instrument")
        or row.get("market")
        or ""
    )
    if pair and "-" in pair:
        return pair == f"{base}-{quote}"
    aid = str(row.get("aid", "")).upper()
    price_ccy = str(row.get("pc", "")).upper()
    qty_ccy = str(row.get("qc", "")).upper()
    return aid == base and price_ccy == quote and qty_ccy == base


def _parse_size(trade: dict[str, Any]) -> float:
    for key in ("q", "s", "sz", "size", "amount", "v"):
        size = _to_float(trade.get(key))
        if size is not None and size > 0:
            return size
    return 1.0


@dataclass(frozen=True)
class SourceMeta:
    source: str
    received_ts_epoch: float
    exchange_ts_epoch: float | None
    endpoint: str


@dataclass(frozen=True)
class TickerUpdate:
    symbol: str
    price: float
    source: SourceMeta


@dataclass(frozen=True)
class OrderBookLevel:
    price: float
    size: float
    ts_epoch: float | None = None


@dataclass(frozen=True)
class OrderBookUpdate:
    symbol: str
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    source: SourceMeta


@dataclass(frozen=True)
class TradeUpdate:
    symbol: str
    price: float
    size: float
    ts_epoch: float
    source: SourceMeta


@dataclass(frozen=True)
class CandleUpdate:
    symbol: str
    timeframe: str
    open_time: int
    close_time: int | None
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: SourceMeta


def fetch_order_book_update(
    symbol: str,
    *,
    cfg: dict | None = None,
    fetcher: Callable[..., Any] | None = None,
) -> OrderBookUpdate | None:
    source_symbol = normalize_symbol(symbol)
    if not source_symbol or "-" not in source_symbol:
        return None
    base, quote = _split_symbol(source_symbol)
    received_at = time.time()
    fn = fetcher or get_order_book
    payload = fn(source_symbol, cfg=cfg)
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if not isinstance(data, dict) and isinstance(payload, dict):
        data = payload
    if not isinstance(data, dict):
        data = {}
    raw_asks = data.get("asks")
    raw_bids = data.get("bids")
    if not isinstance(raw_asks, list) or not isinstance(raw_bids, list):
        return None

    asks: list[OrderBookLevel] = []
    bids: list[OrderBookLevel] = []
    for row in raw_asks:
        if not isinstance(row, dict) or not _matches_symbol_row(row, base, quote):
            continue
        side = str(row.get("s", "")).upper()
        if side and side != "SELL":
            continue
        px = _to_float(row.get("p"))
        sz = _to_float(row.get("q"))
        if px is None or sz is None or px <= 0 or sz <= 0:
            continue
        asks.append(OrderBookLevel(price=px, size=sz, ts_epoch=_parse_ts(row)))

    for row in raw_bids:
        if not isinstance(row, dict) or not _matches_symbol_row(row, base, quote):
            continue
        side = str(row.get("s", "")).upper()
        if side and not side.startswith("BUY"):
            continue
        px = _to_float(row.get("p"))
        sz = _to_float(row.get("q"))
        if px is None or sz is None or px <= 0 or sz <= 0:
            continue
        bids.append(OrderBookLevel(price=px, size=sz, ts_epoch=_parse_ts(row)))

    if not asks or not bids:
        return None

    asks.sort(key=lambda row: row.price)
    bids.sort(key=lambda row: row.price, reverse=True)
    exchange_ts = _parse_ts(payload.get("metadata", {})) if isinstance(payload, dict) else None
    source = SourceMeta(
        source="revolut",
        received_ts_epoch=float(received_at),
        exchange_ts_epoch=exchange_ts,
        endpoint="order_book",
    )
    return OrderBookUpdate(
        symbol=source_symbol,
        bids=tuple(bids),
        asks=tuple(asks),
        source=source,
    )


def fetch_trade_updates(
    symbol: str,
    *,
    limit: int,
    fetcher: Callable[..., Any] | None = None,
) -> list[TradeUpdate]:
    source_symbol = normalize_symbol(symbol)
    if not source_symbol or "-" not in source_symbol:
        return []
    base, quote = _split_symbol(source_symbol)
    received_at = time.time()
    fn = fetcher or get_last_trades
    payload = fn(symbol=source_symbol, limit=int(limit))
    rows = payload
    if isinstance(payload, dict):
        for key in ("data", "trades", "items", "result"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                rows = candidate
                break
    if not isinstance(rows, list):
        return []

    out: list[TradeUpdate] = []
    for row in rows:
        if not isinstance(row, dict) or not _matches_symbol_row(row, base, quote):
            continue
        ts = _parse_ts(row)
        px = _to_float(row.get("p"))
        if ts is None or px is None or px <= 0:
            continue
        if ts > (time.time() + FUTURE_TRADE_TOLERANCE_SECONDS):
            continue
        source = SourceMeta(
            source="revolut",
            received_ts_epoch=float(received_at),
            exchange_ts_epoch=ts,
            endpoint="trades",
        )
        out.append(
            TradeUpdate(
                symbol=source_symbol,
                price=px,
                size=_parse_size(row),
                ts_epoch=ts,
                source=source,
            )
        )
    out.sort(key=lambda row: row.ts_epoch)
    return out
