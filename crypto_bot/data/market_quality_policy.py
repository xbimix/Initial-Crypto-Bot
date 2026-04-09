from __future__ import annotations

from dataclasses import dataclass

from data.revolut_candle_fetcher import timeframe_to_interval_minutes


@dataclass(frozen=True)
class FreshnessPolicy:
    timeframe: str
    interval_minutes: int
    stale_intervals: int
    min_stale_seconds: int
    stale_after_seconds: int


def _parse_timeframe_minutes(timeframe: str) -> int:
    raw = str(timeframe or "").strip().lower()
    if not raw:
        return 1
    try:
        return max(int(timeframe_to_interval_minutes(raw)), 1)
    except Exception:
        pass
    try:
        if raw.endswith("m"):
            return max(int(raw[:-1]), 1)
        if raw.endswith("h"):
            return max(int(raw[:-1]) * 60, 1)
        if raw.endswith("d"):
            return max(int(raw[:-1]) * 1440, 1)
        if raw.endswith("w"):
            return max(int(raw[:-1]) * 10080, 1)
    except Exception:
        return 1
    return 1


def resolve_freshness_policy(
    *,
    timeframe: str,
    stale_intervals: int = 3,
    min_stale_seconds: int = 300,
) -> FreshnessPolicy:
    interval_minutes = _parse_timeframe_minutes(timeframe)
    clean_intervals = max(int(stale_intervals or 0), 1)
    clean_min_seconds = max(int(min_stale_seconds or 0), 60)
    stale_after_seconds = max(
        clean_min_seconds,
        int(interval_minutes) * 60 * clean_intervals,
    )
    return FreshnessPolicy(
        timeframe=str(timeframe or "").strip().lower() or "1m",
        interval_minutes=int(interval_minutes),
        stale_intervals=int(clean_intervals),
        min_stale_seconds=int(clean_min_seconds),
        stale_after_seconds=int(stale_after_seconds),
    )

