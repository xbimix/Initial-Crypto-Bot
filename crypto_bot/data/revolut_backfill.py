from __future__ import annotations

import time

from data.revolut_candle_fetcher import (
    MAX_CANDLES_PER_REQUEST,
    fetch_candles,
    timeframe_to_interval_minutes,
)
from data.revolut_candle_store import RevolutCandleStore


def _iter_request_windows(
    start_ms: int,
    end_ms: int,
    *,
    interval_minutes: int,
) -> list[tuple[int, int]]:
    if end_ms <= start_ms:
        return []
    interval_ms = int(interval_minutes) * 60_000
    window_span = interval_ms * MAX_CANDLES_PER_REQUEST
    cursor = int(start_ms)
    windows: list[tuple[int, int]] = []
    while cursor <= int(end_ms):
        window_end = min(cursor + window_span - 1, int(end_ms))
        windows.append((cursor, window_end))
        cursor = window_end + 1
    return windows


def backfill_symbol_timeframe(
    symbol: str,
    timeframe: str,
    target_start_ms: int,
    target_end_ms: int,
    *,
    db_path=None,
    source: str = "revolut",
    batch_pages: int = 20,
    sleep_seconds: float = 0.0,
) -> dict:
    now_ms = int(time.time() * 1000)
    if target_end_ms <= target_start_ms:
        store = RevolutCandleStore(db_path=db_path)
        earliest = store.get_earliest_open_time(symbol, timeframe)
        latest = store.get_latest_open_time(symbol, timeframe)
        store.upsert_sync_state(
            symbol=symbol,
            timeframe=timeframe,
            earliest_ms=earliest,
            latest_ms=latest,
            last_sync_ms=now_ms,
            status="skipped",
            note="target_window_invalid",
        )
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "requests": 0,
            "candles_fetched": 0,
            "candles_upserted": 0,
            "checkpoint_status": "skipped",
            "ranges": [],
        }

    store = RevolutCandleStore(db_path=db_path)
    interval_minutes = timeframe_to_interval_minutes(timeframe)
    ranges = store.find_missing_ranges(
        symbol=symbol,
        timeframe=timeframe,
        target_start_ms=int(target_start_ms),
        target_end_ms=int(target_end_ms),
    )

    requests = 0
    candles_fetched = 0
    candles_upserted = 0
    pages_since_pause = 0

    checkpoint_status = "ok"
    checkpoint_note = "complete"
    try:
        for range_start, range_end in ranges:
            for since_ms, until_ms in _iter_request_windows(
                range_start,
                range_end,
                interval_minutes=interval_minutes,
            ):
                candles = fetch_candles(
                    symbol=symbol,
                    interval_minutes=interval_minutes,
                    since_ms=since_ms,
                    until_ms=until_ms,
                )
                requests += 1
                candles_fetched += len(candles)
                candles_upserted += store.upsert(
                    symbol=symbol,
                    timeframe=timeframe,
                    candles=candles,
                    source=source,
                )
                pages_since_pause += 1
                if sleep_seconds > 0 and pages_since_pause >= max(int(batch_pages), 1):
                    time.sleep(float(sleep_seconds))
                    pages_since_pause = 0
    except Exception as exc:
        checkpoint_status = "error"
        checkpoint_note = f"backfill_failed:{type(exc).__name__}"
        raise
    finally:
        earliest = store.get_earliest_open_time(symbol, timeframe)
        latest = store.get_latest_open_time(symbol, timeframe)
        store.upsert_sync_state(
            symbol=symbol,
            timeframe=timeframe,
            earliest_ms=earliest,
            latest_ms=latest,
            last_sync_ms=int(time.time() * 1000),
            status=checkpoint_status,
            note=checkpoint_note,
        )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "requests": requests,
        "candles_fetched": candles_fetched,
        "candles_upserted": candles_upserted,
        "checkpoint_status": checkpoint_status,
        "ranges": ranges,
    }
