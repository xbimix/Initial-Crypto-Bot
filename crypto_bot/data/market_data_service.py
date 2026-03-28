from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from data.data_quality import QualityInput, resolve_quality
from data.revolut_candle_fetcher import timeframe_to_interval_minutes
from data.revolut_candle_store import RevolutCandleStore
from data.revolut_market_db import resolve_db_path
from data.revolut_orderbook_cache import get_orderbook_cache, update_orderbook_cache


class MarketDataService:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = resolve_db_path(db_path)
        self.store = RevolutCandleStore(self.db_path)

    def get_candles(self, symbol: str, timeframe: str, limit: int | None = None) -> list[dict]:
        return self.store.get_candles(symbol=symbol, timeframe=timeframe, limit=limit, ascending=True)

    def get_latest_closed_candle(self, symbol: str, timeframe: str) -> dict | None:
        rows = self.store.get_candles(symbol=symbol, timeframe=timeframe, limit=2500, ascending=False)
        if not rows:
            return None
        now_ms = int(time.time() * 1000)
        interval_ms = timeframe_to_interval_minutes(timeframe) * 60_000
        for row in rows:
            close_time = row.get("close_time")
            candle_close = int(close_time) if close_time is not None else int(row["open_time"]) + interval_ms
            if candle_close <= now_ms:
                return row
        return None

    def get_candle_meta(
        self,
        symbol: str,
        timeframe: str,
        *,
        stale_after_seconds: int = 120,
    ) -> dict:
        supported_timeframe = True
        try:
            timeframe_to_interval_minutes(timeframe)
        except Exception:
            supported_timeframe = False

        latest_open = None
        earliest_open = None
        count = 0
        updated_at = None
        quality_reason = "ok"
        try:
            latest_open = self.store.get_latest_open_time(symbol, timeframe)
            earliest_open = self.store.get_earliest_open_time(symbol, timeframe)
            count = self.store.get_count(symbol, timeframe)
            updated_at = self.store.get_last_updated_at(symbol, timeframe)
        except sqlite3.OperationalError:
            # Keep timeframe support semantics intact on transient DB contention.
            quality_reason = "meta_fetch_failed"
        except Exception:
            quality_reason = "meta_fetch_failed"
        now_ms = int(time.time() * 1000)
        stale = True
        if updated_at is not None:
            stale = (now_ms - int(updated_at)) > (int(stale_after_seconds) * 1000)
        quality = resolve_quality(
            QualityInput(
                sample_count=int(count or 0),
                min_required=120,
                stale=bool(stale),
                supported=bool(supported_timeframe),
                reason=quality_reason if quality_reason != "ok" else ("stale_data" if stale else "ok"),
            )
        )
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "last_update_ts": updated_at,
            "candle_count": count,
            "earliest_open_time": earliest_open,
            "latest_open_time": latest_open,
            "stale": stale,
            "source": "revolut",
            "supported": supported_timeframe,
            "supported_timeframe": supported_timeframe,
            "data_quality": quality,
            "status": quality.get("status"),
            "reason": quality.get("reason"),
        }

    def get_orderbook_top5(
        self,
        symbol: str,
        *,
        refresh_if_stale: bool = True,
        stale_after_seconds: int = 10,
    ) -> dict | None:
        cached = get_orderbook_cache(symbol)
        if cached is None and refresh_if_stale:
            cached = update_orderbook_cache(symbol)
        elif cached is not None and refresh_if_stale:
            now_ms = int(time.time() * 1000)
            age_ms = now_ms - int(cached["ts"])
            if age_ms > int(stale_after_seconds) * 1000:
                cached = update_orderbook_cache(symbol)

        if cached is None:
            return None
        now_ms = int(time.time() * 1000)
        age_seconds = max(0.0, (now_ms - int(cached["ts"])) / 1000.0)
        payload = dict(cached)
        payload["staleness_seconds"] = age_seconds
        payload["source"] = payload.get("source", "revolut")
        return payload


_default_service: MarketDataService | None = None


def _service() -> MarketDataService:
    global _default_service
    if _default_service is None:
        _default_service = MarketDataService()
    return _default_service


def get_candles(symbol: str, timeframe: str, limit: int | None = None) -> list[dict]:
    return _service().get_candles(symbol=symbol, timeframe=timeframe, limit=limit)


def get_latest_closed_candle(symbol: str, timeframe: str) -> dict | None:
    return _service().get_latest_closed_candle(symbol=symbol, timeframe=timeframe)


def get_candle_meta(
    symbol: str,
    timeframe: str,
    *,
    stale_after_seconds: int = 120,
) -> dict:
    return _service().get_candle_meta(
        symbol=symbol,
        timeframe=timeframe,
        stale_after_seconds=stale_after_seconds,
    )


def get_orderbook_top5(symbol: str) -> dict | None:
    return _service().get_orderbook_top5(symbol=symbol)
