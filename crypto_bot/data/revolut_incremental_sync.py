from __future__ import annotations

import json
import os
import time
from pathlib import Path

from data.revolut_candle_fetcher import (
    MAX_CANDLES_PER_REQUEST,
    RevolutCandleFetchError,
    fetch_candles,
    timeframe_to_interval_minutes,
)
from data.revolut_candle_store import RevolutCandleStore

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
PRICE_HISTORY_PATH = STATE_DIR / "revolut_universe_price_history.json"
DEFAULT_BOOTSTRAP_LOOKBACK_DAYS = {
    "1m": 7,
    "5m": 30,
    "15m": 90,
    "30m": 90,
    "1h": 180,
    "4h": 365,
    "1d": 365,
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _market_data_cfg(cfg: dict | None) -> dict:
    if not isinstance(cfg, dict):
        return {}
    raw = cfg.get("market_data", {})
    return raw if isinstance(raw, dict) else {}


def _candle_source_map(cfg: dict | None) -> dict:
    market_data_cfg = _market_data_cfg(cfg)
    source_map = market_data_cfg.get("source_map", {})
    if not isinstance(source_map, dict):
        return {}
    candles = source_map.get("candles", {})
    return candles if isinstance(candles, dict) else {}


def _resolve_candle_public_fallback(cfg: dict | None, override: bool | None) -> bool:
    if isinstance(override, bool):
        return override
    source_map = _candle_source_map(cfg)
    if "allow_public_fallback" in source_map:
        return bool(source_map.get("allow_public_fallback"))
    return _env_bool("REVBOT_CANDLE_ALLOW_PUBLIC_FALLBACK", default=False)


def _resolve_snapshot_fallback(cfg: dict | None, override: bool | None) -> bool:
    if isinstance(override, bool):
        return override
    source_map = _candle_source_map(cfg)
    if "allow_snapshot_fallback" in source_map:
        return bool(source_map.get("allow_snapshot_fallback"))
    return _env_bool("REVBOT_ALLOW_SNAPSHOT_CANDLE_FALLBACK", default=False)


def _bootstrap_lookback_days(timeframe: str) -> int:
    tf = str(timeframe or "").strip().lower()
    env_name = f"REVBOT_BOOTSTRAP_LOOKBACK_DAYS_{tf.upper()}"
    raw = os.getenv(env_name)
    if raw is not None:
        try:
            days = int(float(raw))
            if days > 0:
                return days
        except (TypeError, ValueError):
            pass
    return int(DEFAULT_BOOTSTRAP_LOOKBACK_DAYS.get(tf, 30))


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


def _derive_candles_from_price_history(
    *,
    symbol: str,
    interval_ms: int,
    since_ms: int,
    until_ms: int,
) -> list[dict]:
    if interval_ms <= 0 or until_ms <= since_ms:
        return []
    try:
        payload = json.loads(PRICE_HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get(str(symbol).strip().upper())
    if not isinstance(rows, list):
        return []

    buckets: dict[int, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts_raw = row.get("ts")
        px_raw = row.get("price")
        try:
            ts_ms = int(float(ts_raw) * 1000.0)
            px = float(px_raw)
        except (TypeError, ValueError):
            continue
        if px <= 0 or ts_ms < since_ms or ts_ms > until_ms:
            continue
        bucket_start = (ts_ms // interval_ms) * interval_ms
        if bucket_start < since_ms:
            continue
        cell = buckets.get(bucket_start)
        if cell is None:
            buckets[bucket_start] = {
                "ts": bucket_start,
                "open": px,
                "high": px,
                "low": px,
                "close": px,
                "volume": 0.0,
                "close_time": bucket_start + interval_ms - 1,
            }
            continue
        cell["high"] = max(float(cell["high"]), px)
        cell["low"] = min(float(cell["low"]), px)
        cell["close"] = px

    return [buckets[key] for key in sorted(buckets.keys())]


def sync_new_candles(
    symbol: str,
    timeframe: str,
    *,
    db_path=None,
    now_ms: int | None = None,
    source: str = "revolut",
    include_partial: bool = False,
    cfg: dict | None = None,
    allow_public_fallback: bool | None = None,
    allow_snapshot_fallback: bool | None = None,
) -> dict:
    store = RevolutCandleStore(db_path=db_path)
    interval_minutes = timeframe_to_interval_minutes(timeframe)
    interval_ms = interval_minutes * 60_000
    current_ms = int(now_ms if now_ms is not None else time.time() * 1000)

    latest_open_time = store.get_latest_open_time(symbol, timeframe)
    if latest_open_time is None:
        bootstrap_days = _bootstrap_lookback_days(timeframe)
        since_ms = max(0, current_ms - (bootstrap_days * 24 * 60 * 60 * 1000))
    else:
        since_ms = int(latest_open_time + interval_ms)

    if since_ms > current_ms:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "fetched": 0,
            "inserted": 0,
            "new_inserted": 0,
            "updated_existing": 0,
            "candidate_new": 0,
            "eligible_closed": 0,
            "skipped_existing": 0,
            "skipped_partial": 0,
            "partial_count": 0,
            "requests": 0,
            "latest_open_time": latest_open_time,
        }

    fetched: list[dict] = []
    requests = 0
    effective_source = source
    sync_status = "ok"
    sync_note = "incremental_sync"
    resolved_public_fallback = _resolve_candle_public_fallback(cfg, allow_public_fallback)
    resolved_snapshot_fallback = _resolve_snapshot_fallback(cfg, allow_snapshot_fallback)
    try:
        for window_since, window_until in _iter_request_windows(
            since_ms,
            current_ms,
            interval_minutes=interval_minutes,
        ):
            try:
                window_rows = fetch_candles(
                    symbol=symbol,
                    interval_minutes=interval_minutes,
                    since_ms=window_since,
                    until_ms=window_until,
                    allow_public_fallback=resolved_public_fallback,
                )
            except TypeError:
                # Backward-compat for test doubles/custom monkeypatches.
                window_rows = fetch_candles(
                    symbol=symbol,
                    interval_minutes=interval_minutes,
                    since_ms=window_since,
                    until_ms=window_until,
                )
            fetched.extend(window_rows)
            requests += 1
    except RevolutCandleFetchError as exc:
        if not exc.permanent:
            raise
        if resolved_snapshot_fallback:
            fetched = _derive_candles_from_price_history(
                symbol=symbol,
                interval_ms=interval_ms,
                since_ms=since_ms,
                until_ms=current_ms,
            )
            effective_source = "snapshot_derived"
            sync_status = "degraded"
            sync_note = f"official_candles_unavailable:{exc}"
        else:
            fetched = []
            effective_source = "revolut"
            sync_status = "unsupported"
            sync_note = f"official_candles_unavailable_no_fallback:{exc}"

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
    pre_count = int(store.get_count(symbol, timeframe) or 0)
    inserted = store.upsert(
        symbol=symbol,
        timeframe=timeframe,
        candles=rows_to_store,
        source=effective_source,
    )
    latest_after = store.get_latest_open_time(symbol, timeframe)
    post_count = int(store.get_count(symbol, timeframe) or 0)
    new_inserted = max(0, post_count - pre_count)
    updated_existing = max(0, int(inserted) - int(new_inserted))
    skipped_existing = max(0, int(len(fetched)) - int(len(new_rows)))
    skipped_partial = int(len(partial_rows)) if not include_partial else 0
    store.upsert_sync_state(
        symbol=symbol,
        timeframe=timeframe,
        earliest_ms=store.get_earliest_open_time(symbol, timeframe),
        latest_ms=latest_after,
        last_sync_ms=current_ms,
        status=sync_status,
        note=sync_note,
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "fetched": len(fetched),
        "inserted": inserted,
        "new_inserted": new_inserted,
        "updated_existing": updated_existing,
        "candidate_new": len(new_rows),
        "eligible_closed": len(closed_rows),
        "skipped_existing": skipped_existing,
        "skipped_partial": skipped_partial,
        "partial_count": len(partial_rows),
        "requests": requests,
        "latest_open_time": latest_after,
        "source": effective_source,
        "status": sync_status,
        "note": sync_note,
        "allow_public_fallback": bool(resolved_public_fallback),
        "allow_snapshot_fallback": bool(resolved_snapshot_fallback),
    }
