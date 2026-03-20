from __future__ import annotations

from datetime import datetime

from api.revolut_api import _get


MAX_CANDLES_PER_REQUEST = 1000
SUPPORTED_INTERVALS_MINUTES = {
    1,
    5,
    15,
    30,
    60,
    240,
    1440,
    2880,
    5760,
    10080,
    20160,
    40320,
}


def _parse_timestamp_ms(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        val = float(value)
        if val <= 0:
            return None
        if val >= 100_000_000_000:
            return int(val)
        if val >= 1_000_000_000:
            return int(val * 1000)
        return int(val)
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return None
        try:
            return _parse_timestamp_ms(float(txt))
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except ValueError:
            return None
    return None


def interval_minutes_to_internal_timeframe(interval_minutes: int) -> str:
    interval = int(interval_minutes)
    if interval not in SUPPORTED_INTERVALS_MINUTES:
        raise ValueError(f"Unsupported Revolut interval minutes: {interval}")
    if interval < 60:
        return f"{interval}m"
    if interval % 10080 == 0:
        return f"{interval // 10080}w"
    if interval % 1440 == 0:
        return f"{interval // 1440}d"
    if interval % 60 == 0:
        return f"{interval // 60}h"
    return f"{interval}m"


def timeframe_to_interval_minutes(timeframe: str) -> int:
    raw = str(timeframe).strip().lower()
    if not raw:
        raise ValueError("timeframe cannot be empty")

    aliases = {
        "1min": "1m",
        "5min": "5m",
        "15min": "15m",
        "30min": "30m",
        "1hour": "1h",
        "4hour": "4h",
        "1day": "1d",
    }
    norm = aliases.get(raw, raw)
    unit = norm[-1]
    value = int(norm[:-1])

    if unit == "m":
        interval = value
    elif unit == "h":
        interval = value * 60
    elif unit == "d":
        interval = value * 1440
    elif unit == "w":
        interval = value * 10080
    else:
        raise ValueError(f"Unsupported timeframe unit: {timeframe}")

    if interval not in SUPPORTED_INTERVALS_MINUTES:
        raise ValueError(f"Unsupported timeframe for Revolut candles: {timeframe}")
    return interval


def normalize_revolut_candles(raw_response) -> list[dict]:
    if raw_response is None:
        return []

    rows = raw_response
    if isinstance(raw_response, dict):
        for key in ("data", "candles", "items", "result"):
            candidate = raw_response.get(key)
            if isinstance(candidate, list):
                rows = candidate
                break

    if not isinstance(rows, list):
        return []

    normalized: dict[int, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue

        open_time = _parse_timestamp_ms(
            row.get("open_time", row.get("t", row.get("ts", row.get("time"))))
        )
        close_time = _parse_timestamp_ms(
            row.get("close_time", row.get("T", row.get("end_time")))
        )
        if open_time is None:
            continue

        def _value(*keys):
            for key in keys:
                if key in row and row[key] is not None:
                    try:
                        return float(row[key])
                    except (TypeError, ValueError):
                        return None
            return None

        open_px = _value("open", "o")
        high_px = _value("high", "h")
        low_px = _value("low", "l")
        close_px = _value("close", "c")
        volume = _value("volume", "v")

        if None in (open_px, high_px, low_px, close_px):
            continue

        normalized[open_time] = {
            "ts": int(open_time),
            "open": float(open_px),
            "high": float(high_px),
            "low": float(low_px),
            "close": float(close_px),
            "volume": float(volume) if volume is not None else 0.0,
            "close_time": int(close_time) if close_time is not None else None,
        }

    return [normalized[key] for key in sorted(normalized.keys())]


def fetch_candles(
    symbol: str,
    interval_minutes: int,
    since_ms: int,
    until_ms: int,
) -> list[dict]:
    interval = int(interval_minutes)
    if interval not in SUPPORTED_INTERVALS_MINUTES:
        raise ValueError(f"Unsupported interval minutes: {interval}")
    if int(until_ms) <= int(since_ms):
        return []

    interval_ms = interval * 60_000
    expected = ((int(until_ms) - int(since_ms)) // interval_ms) + 1
    if expected > MAX_CANDLES_PER_REQUEST:
        raise ValueError(
            f"Requested {expected} candles; Revolut limit is {MAX_CANDLES_PER_REQUEST} per call"
        )

    payload = _get(
        "/public/candles",
        params={
            "symbol": str(symbol),
            "interval": interval,
            "since": int(since_ms),
            "until": int(until_ms),
        },
        auth=False,
    )
    return normalize_revolut_candles(payload)
