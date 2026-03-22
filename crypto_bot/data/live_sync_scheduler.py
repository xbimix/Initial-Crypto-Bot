from __future__ import annotations

import time
from typing import Any

from data.revolut_incremental_sync import sync_new_candles


DEFAULT_TIMEFRAMES = ["1h", "4h", "1d"]
CORE_TIMEFRAME_PRIORITY = {"1h": 0, "4h": 1, "1d": 2}
DEFAULT_CADENCE_SECONDS = {
    "1m": 20,
    "5m": 60,
    "15m": 180,
    "1h": 420,
    "4h": 1200,
    "1d": 2700,
}

_last_sync_at: dict[tuple[str, str], float] = {}


def _to_int(value: Any, fallback: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def _market_data_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = cfg.get("market_data", {})
    return raw if isinstance(raw, dict) else {}


def _enabled(cfg: dict[str, Any]) -> bool:
    raw = _market_data_cfg(cfg).get("incremental_sync_enabled", True)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return True


def _timeframes(cfg: dict[str, Any]) -> list[str]:
    value = _market_data_cfg(cfg).get("sync_timeframes", DEFAULT_TIMEFRAMES)
    if not isinstance(value, list):
        return list(DEFAULT_TIMEFRAMES)
    out: list[str] = []
    for row in value:
        tf = str(row).strip().lower()
        if tf and tf not in out:
            out.append(tf)
    return out or list(DEFAULT_TIMEFRAMES)


def _cadence_map(cfg: dict[str, Any]) -> dict[str, int]:
    output = dict(DEFAULT_CADENCE_SECONDS)
    raw = _market_data_cfg(cfg).get("sync_cadence_seconds", {})
    if isinstance(raw, dict):
        for timeframe, seconds in raw.items():
            tf = str(timeframe).strip().lower()
            if not tf:
                continue
            output[tf] = max(1, _to_int(seconds, output.get(tf, 60)))
    return output


def _max_requests(cfg: dict[str, Any]) -> int:
    return max(1, _to_int(_market_data_cfg(cfg).get("max_sync_requests_per_tick", 8), 8))


def _error_backoff_seconds(cfg: dict[str, Any]) -> int:
    return max(1, _to_int(_market_data_cfg(cfg).get("sync_error_backoff_seconds", 60), 60))


def _stagger_seconds(symbol: str, timeframe: str, cadence_seconds: int) -> float:
    # Stable per-symbol/per-timeframe offset to prevent synchronized request bursts.
    bucket = abs(hash(f"{symbol}:{timeframe}")) % 1000
    ratio = bucket / 1000.0
    max_stagger = min(float(cadence_seconds), 15.0)
    return ratio * max_stagger


def run_incremental_sync_tick(
    *,
    cfg: dict[str, Any],
    symbols: list[str],
    now_epoch: float | None = None,
) -> dict[str, Any]:
    if not _enabled(cfg):
        return {"enabled": False, "requests": 0, "inserted": 0, "errors": 0, "jobs": []}

    now = float(now_epoch if now_epoch is not None else time.time())
    timeframes = _timeframes(cfg)
    cadence = _cadence_map(cfg)
    request_cap = _max_requests(cfg)
    error_backoff_seconds = _error_backoff_seconds(cfg)

    jobs: list[dict[str, Any]] = []
    attempted_jobs = 0
    requests = 0
    inserted = 0
    errors = 0
    degraded = 0
    unique_symbols = []
    seen = set()
    for raw in symbols:
        symbol = str(raw).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        unique_symbols.append(symbol)

    due_jobs: list[tuple[float, int, str, str, int]] = []
    for symbol in unique_symbols:
        for timeframe in timeframes:
            cadence_seconds = max(1, int(cadence.get(timeframe, 60)))
            key = (symbol, timeframe)
            last = _last_sync_at.get(key)
            stagger = _stagger_seconds(symbol, timeframe, cadence_seconds)
            due = False
            if last is None:
                due = now >= stagger
            else:
                due = (now - last) >= cadence_seconds
            if not due:
                continue
            # Oldest sync first; prefer core windows when equally old.
            sort_last = float(last) if last is not None else 0.0
            tf_priority = int(CORE_TIMEFRAME_PRIORITY.get(timeframe, 9))
            tie_break = abs(hash(f"{symbol}:{timeframe}")) % 10000
            due_jobs.append((sort_last, tf_priority, tie_break, symbol, timeframe, cadence_seconds))

    due_jobs.sort(key=lambda row: (row[0], row[1], row[2], row[3], row[4]))
    selected_jobs = due_jobs[: max(1, request_cap)]

    for _, _, _, symbol, timeframe, cadence_seconds in selected_jobs:
        key = (symbol, timeframe)
        attempted_jobs += 1
        next_delay_seconds = cadence_seconds
        try:
            result = sync_new_candles(symbol=symbol, timeframe=timeframe, include_partial=False)
            result_status = str(result.get("status", "ok")).strip().lower()
            requests += int(result.get("requests", 0) or 0)
            inserted += int(result.get("inserted", 0) or 0)
            if result_status in {"degraded", "unsupported"}:
                degraded += 1
            jobs.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "status": result_status or "ok",
                    "fetched": int(result.get("fetched", 0) or 0),
                    "inserted": int(result.get("inserted", 0) or 0),
                    "source": result.get("source"),
                    "note": result.get("note"),
                }
            )
        except Exception as exc:
            errors += 1
            next_delay_seconds = min(cadence_seconds, error_backoff_seconds)
            jobs.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "status": "error",
                    "error": str(exc),
                }
            )
        finally:
            _last_sync_at[key] = now - cadence_seconds + float(next_delay_seconds)

    return {
        "enabled": True,
        "attempted_jobs": attempted_jobs,
        "requests": requests,
        "inserted": inserted,
        "errors": errors,
        "degraded": degraded,
        "jobs": jobs,
    }
