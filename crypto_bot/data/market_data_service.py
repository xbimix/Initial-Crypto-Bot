from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from data.data_quality import QualityInput, resolve_quality
from data.market_quality_policy import resolve_freshness_policy
from data.revolut_candle_fetcher import timeframe_to_interval_minutes
from data.revolut_candle_store import RevolutCandleStore
from data.revolut_market_db import resolve_db_path
from data.revolut_orderbook_cache import (
    get_orderbook_cache,
    get_orderbook_cache_metrics,
    update_orderbook_cache,
)


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
        stale_after_seconds: int | None = None,
    ) -> dict:
        requested_tf = str(timeframe or "").strip().lower()
        supported_timeframe = True
        interval_minutes = None
        try:
            interval_minutes = timeframe_to_interval_minutes(requested_tf)
        except Exception:
            supported_timeframe = False

        if stale_after_seconds is None:
            policy = resolve_freshness_policy(
                timeframe=timeframe,
                stale_intervals=3,
                min_stale_seconds=300,
            )
            stale_after_seconds = int(policy.stale_after_seconds)
        else:
            stale_after_seconds = max(int(stale_after_seconds), 1)

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
        interval_ms = int(interval_minutes or 1) * 60_000 if interval_minutes is not None else 60_000
        freshness_reference = "none"
        freshness_reference_ts = None
        age_seconds = None

        # Prefer candle-time freshness over write-time freshness so staleness
        # reflects market-data age rather than storage mutation time.
        if latest_open is not None:
            try:
                freshness_reference_ts = int(latest_open) + int(interval_ms)
                freshness_reference = "latest_candle_close_estimate"
            except (TypeError, ValueError):
                freshness_reference_ts = None
                freshness_reference = "none"
        if freshness_reference_ts is None and updated_at is not None:
            try:
                freshness_reference_ts = int(updated_at)
                freshness_reference = "last_updated_at"
            except (TypeError, ValueError):
                freshness_reference_ts = None
                freshness_reference = "none"

        stale = True
        if freshness_reference_ts is not None:
            age_ms = max(0, int(now_ms - int(freshness_reference_ts)))
            age_seconds = float(age_ms) / 1000.0
            stale = age_ms > (int(stale_after_seconds) * 1000)
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
            "freshness_reference_ts": freshness_reference_ts,
            "freshness_reference": freshness_reference,
            "age_seconds": age_seconds,
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
            if bool(cached.get("stale")):
                cached = update_orderbook_cache(symbol)
            else:
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
        payload["cache_metrics"] = get_orderbook_cache_metrics()
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
    stale_after_seconds: int | None = None,
) -> dict:
    return _service().get_candle_meta(
        symbol=symbol,
        timeframe=timeframe,
        stale_after_seconds=stale_after_seconds,
    )


def get_orderbook_top5(symbol: str) -> dict | None:
    return _service().get_orderbook_top5(symbol=symbol)
