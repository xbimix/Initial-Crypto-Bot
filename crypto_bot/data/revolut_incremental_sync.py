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


def sync_new_candles(
    symbol: str,
    timeframe: str,
    *,
    db_path=None,
    now_ms: int | None = None,
    source: str = "revolut",
    include_partial: bool = False,
) -> dict:
    store = RevolutCandleStore(db_path=db_path)
    interval_minutes = timeframe_to_interval_minutes(timeframe)
    interval_ms = interval_minutes * 60_000
    current_ms = int(now_ms if now_ms is not None else time.time() * 1000)

    latest_open_time = store.get_latest_open_time(symbol, timeframe)
    if latest_open_time is None:
        since_ms = max(0, current_ms - (interval_ms * 1000))
    else:
        since_ms = int(latest_open_time + interval_ms)

    if since_ms > current_ms:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "fetched": 0,
            "inserted": 0,
            "partial_count": 0,
            "requests": 0,
            "latest_open_time": latest_open_time,
        }

    fetched: list[dict] = []
    requests = 0
    for window_since, window_until in _iter_request_windows(
        since_ms,
        current_ms,
        interval_minutes=interval_minutes,
    ):
        window_rows = fetch_candles(
            symbol=symbol,
            interval_minutes=interval_minutes,
            since_ms=window_since,
            until_ms=window_until,
        )
        fetched.extend(window_rows)
        requests += 1

    new_rows = [row for row in fetched if latest_open_time is None or int(row["ts"]) > int(latest_open_time)]
    closed_rows: list[dict] = []
    partial_rows: list[dict] = []
    for row in new_rows:
        close_time = row.get("close_time")
        candle_close = int(close_time) if close_time is not None else int(row["ts"]) + interval_ms
        if candle_close <= current_ms:
            closed_rows.append(row)
        else:
            partial_rows.append(row)

    rows_to_store = new_rows if include_partial else closed_rows
    inserted = store.upsert(symbol=symbol, timeframe=timeframe, candles=rows_to_store, source=source)
    latest_after = store.get_latest_open_time(symbol, timeframe)
    store.upsert_sync_state(
        symbol=symbol,
        timeframe=timeframe,
        earliest_ms=store.get_earliest_open_time(symbol, timeframe),
        latest_ms=latest_after,
        last_sync_ms=current_ms,
        status="ok",
        note="incremental_sync",
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "fetched": len(fetched),
        "inserted": inserted,
        "partial_count": len(partial_rows),
        "requests": requests,
        "latest_open_time": latest_after,
    }
