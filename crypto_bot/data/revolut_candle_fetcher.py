from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

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

_WORKING_CANDLE_REQUEST: dict[str, Any] | None = None
_CANDLE_SCOPE_UNAUTHORIZED_UNTIL_EPOCH: float = 0.0


def _scope_cooldown_seconds() -> float:
    raw = os.getenv("REVBOT_CANDLE_SCOPE_COOLDOWN_SECONDS", "900")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 900.0
    return max(60.0, value)


class RevolutCandleFetchError(RuntimeError):
    def __init__(self, message: str, *, permanent: bool = False):
        super().__init__(message)
        self.permanent = bool(permanent)


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
            row.get(
                "open_time",
                row.get("t", row.get("ts", row.get("time", row.get("start")))),
            )
        )
        close_time = _parse_timestamp_ms(
            row.get("close_time", row.get("T", row.get("end_time", row.get("end"))))
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
    global _WORKING_CANDLE_REQUEST
    global _CANDLE_SCOPE_UNAUTHORIZED_UNTIL_EPOCH

    interval = int(interval_minutes)
    if interval not in SUPPORTED_INTERVALS_MINUTES:
        raise ValueError(f"Unsupported interval minutes: {interval}")
    if int(until_ms) <= int(since_ms):
        return []

    now_epoch = time.time()
    if _CANDLE_SCOPE_UNAUTHORIZED_UNTIL_EPOCH > now_epoch:
        remaining = int(_CANDLE_SCOPE_UNAUTHORIZED_UNTIL_EPOCH - now_epoch)
        raise RevolutCandleFetchError(
            f"Candle endpoint cooldown active due to previous auth scope unauthorized "
            f"(retry_in_seconds={remaining})",
            permanent=True,
        )

    interval_ms = interval * 60_000
    expected = ((int(until_ms) - int(since_ms)) // interval_ms) + 1
    if expected > MAX_CANDLES_PER_REQUEST:
        raise ValueError(
            f"Requested {expected} candles; Revolut limit is {MAX_CANDLES_PER_REQUEST} per call"
        )

    def _to_iso(ms: int) -> str:
        return datetime.utcfromtimestamp(ms / 1000.0).isoformat(timespec="seconds") + "Z"

    params_primary = {
        "symbol": str(symbol),
        "interval": interval,
        "since": int(since_ms),
        "until": int(until_ms),
    }
    params_seconds = {
        "symbol": str(symbol),
        "interval": interval,
        "since": int(since_ms // 1000),
        "until": int(until_ms // 1000),
    }
    params_iso = {
        "symbol": str(symbol),
        "interval": interval,
        "since": _to_iso(int(since_ms)),
        "until": _to_iso(int(until_ms)),
    }
    params_alt_interval = dict(params_primary)
    params_alt_interval["interval_minutes"] = params_alt_interval.pop("interval")
    params_alt_timeframe = dict(params_primary)
    params_alt_timeframe["timeframe"] = interval_minutes_to_internal_timeframe(interval)
    params_alt_timeframe.pop("interval", None)
    params_start_end = {
        "symbol": str(symbol),
        "interval": interval,
        "start": int(since_ms),
        "end": int(until_ms),
    }
    params_start_end_seconds = {
        "symbol": str(symbol),
        "interval": interval,
        "start": int(since_ms // 1000),
        "end": int(until_ms // 1000),
    }
    params_symbolless_primary = {
        "interval": interval,
        "since": int(since_ms),
        "until": int(until_ms),
    }
    params_symbolless_seconds = {
        "interval": interval,
        "since": int(since_ms // 1000),
        "until": int(until_ms // 1000),
    }

    mode_to_params = {
        "primary": params_primary,
        "seconds": params_seconds,
        "iso": params_iso,
        "alt_interval": params_alt_interval,
        "alt_timeframe": params_alt_timeframe,
        "start_end": params_start_end,
        "start_end_seconds": params_start_end_seconds,
        "symbolless_primary": params_symbolless_primary,
        "symbolless_seconds": params_symbolless_seconds,
    }
    allow_public = str(os.getenv("REVBOT_CANDLE_ALLOW_PUBLIC_FALLBACK", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    auth_candidates = [
        # Canonical documented endpoint first.
        {"path": f"/candles/{symbol}", "mode": "symbolless_primary", "auth": True},
        {"path": f"/candles/{symbol}", "mode": "symbolless_seconds", "auth": True},
        {"path": f"/market-data/candles/{symbol}", "mode": "symbolless_primary", "auth": True},
        {"path": f"/market-data/candles/{symbol}", "mode": "symbolless_seconds", "auth": True},
        {"path": f"/market-data/historical-candles/{symbol}", "mode": "symbolless_primary", "auth": True},
        {"path": f"/market-data/historical-candles/{symbol}", "mode": "symbolless_seconds", "auth": True},
        {"path": f"/market-data/{symbol}/candles", "mode": "symbolless_primary", "auth": True},
        {"path": f"/market-data/{symbol}/candles", "mode": "symbolless_seconds", "auth": True},
        {"path": f"/market-data/{symbol}/historical-candles", "mode": "symbolless_primary", "auth": True},
        {"path": f"/market-data/{symbol}/historical-candles", "mode": "symbolless_seconds", "auth": True},
        {"path": f"/historical-candles/{symbol}", "mode": "symbolless_primary", "auth": True},
        {"path": f"/historical-candles/{symbol}", "mode": "symbolless_seconds", "auth": True},
        {"path": "/market-data/candles", "mode": "primary", "auth": True},
        {"path": "/market-data/candles", "mode": "seconds", "auth": True},
        {"path": "/market-data/candles", "mode": "alt_interval", "auth": True},
        {"path": "/market-data/historical-candles", "mode": "primary", "auth": True},
        {"path": "/market-data/historical-candles", "mode": "seconds", "auth": True},
        {"path": "/market-data/historical-candles", "mode": "start_end", "auth": True},
        {"path": "/candles", "mode": "primary", "auth": True},
        {"path": "/candles", "mode": "seconds", "auth": True},
        {"path": "/candles", "mode": "alt_interval", "auth": True},
    ]
    public_candidates = [
        {"path": "/public/candles", "mode": "primary", "auth": False},
        {"path": "/public/candles", "mode": "seconds", "auth": False},
        {"path": "/public/candles", "mode": "iso", "auth": False},
        {"path": "/public/candles", "mode": "alt_interval", "auth": False},
        {"path": "/public/candles", "mode": "alt_timeframe", "auth": False},
        {"path": "/public/candles", "mode": "start_end", "auth": False},
        {"path": "/public/candles", "mode": "start_end_seconds", "auth": False},
        {"path": "/public/market-data/historical-candles", "mode": "primary", "auth": False},
        {"path": "/public/market-data/historical-candles", "mode": "seconds", "auth": False},
        {"path": "/public/market-data/candles", "mode": "primary", "auth": False},
        {"path": "/public/ohlcv", "mode": "primary", "auth": False},
        {"path": "/public/ohlcv", "mode": "seconds", "auth": False},
        {"path": f"/public/market-data/candles/{symbol}", "mode": "symbolless_primary", "auth": False},
        {"path": f"/public/market-data/candles/{symbol}", "mode": "symbolless_seconds", "auth": False},
    ]
    def _run_candidates(
        candidates: list[dict[str, Any]],
        *,
        seen: set[tuple[Any, ...]],
        failures: list[str],
    ) -> tuple[list[dict], bool, bool, int]:
        global _WORKING_CANDLE_REQUEST
        any_retryable_local = False
        all_not_found_or_unsupported_local = True
        auth_401_local = 0

        for candidate in candidates:
            path = str(candidate.get("path") or "").strip()
            mode = str(candidate.get("mode") or "primary")
            params = mode_to_params.get(mode, params_primary)
            auth = bool(candidate.get("auth", False))
            if not path or not isinstance(params, dict):
                continue

            signature = (path, auth, mode, tuple(sorted(params.items())))
            if signature in seen:
                continue
            seen.add(signature)

            try:
                payload = _get(path, params=params, auth=auth)
                rows = normalize_revolut_candles(payload)
                # Enforce requested window even if upstream endpoint returns a broader range.
                rows = [
                    row
                    for row in rows
                    if int(row.get("ts", 0)) >= int(since_ms) and int(row.get("ts", 0)) <= int(until_ms)
                ]
                _WORKING_CANDLE_REQUEST = {"path": path, "mode": mode, "auth": auth}
                return rows, any_retryable_local, all_not_found_or_unsupported_local, auth_401_local
            except Exception as exc:
                response = getattr(exc, "response", None)
                status_code = getattr(response, "status_code", None)
                failures.append(f"{path} auth={auth} status={status_code} err={exc}")
                err_text = str(exc).lower()
                auth_missing = auth and (
                    "api key unavailable" in err_text
                    or "private signing key unavailable" in err_text
                )
                if auth and status_code == 401:
                    auth_401_local += 1
                if status_code in {500, 502, 503, 504, 429}:
                    any_retryable_local = True
                elif status_code is None and not auth_missing:
                    any_retryable_local = True
                if status_code not in {400, 401, 403, 404}:
                    all_not_found_or_unsupported_local = False
                if status_code in {500, 502, 503, 504, 429, None}:
                    continue

        return [], any_retryable_local, all_not_found_or_unsupported_local, auth_401_local

    base_candidates = list(auth_candidates)
    if allow_public:
        base_candidates.extend(public_candidates)
    request_candidates: list[dict[str, Any]] = []
    if isinstance(_WORKING_CANDLE_REQUEST, dict):
        request_candidates.append(_WORKING_CANDLE_REQUEST)
    request_candidates.extend(base_candidates)

    seen: set[tuple[Any, ...]] = set()
    failures: list[str] = []
    rows, any_retryable, all_not_found_or_unsupported, auth_401_count = _run_candidates(
        request_candidates,
        seen=seen,
        failures=failures,
    )
    if rows:
        _CANDLE_SCOPE_UNAUTHORIZED_UNTIL_EPOCH = 0.0
        return rows

    # Automatic safety fallback: if all authenticated probes were unauthorized,
    # attempt public variants even when public fallback is not explicitly enabled.
    if not allow_public and auth_401_count > 0:
        rows_public, any_retryable_public, all_not_found_public, _ = _run_candidates(
            public_candidates,
            seen=seen,
            failures=failures,
        )
        any_retryable = any_retryable or any_retryable_public
        all_not_found_or_unsupported = all_not_found_or_unsupported and all_not_found_public
        if rows_public:
            _CANDLE_SCOPE_UNAUTHORIZED_UNTIL_EPOCH = 0.0
            return rows_public

    if any_retryable:
        raise RevolutCandleFetchError(
            "Revolut candle endpoint temporarily unavailable; retry later",
            permanent=False,
        )

    if all_not_found_or_unsupported:
        scope_hint = "auth_scope_unauthorized" if auth_401_count > 0 else "not_found_or_unsupported"
        if auth_401_count > 0:
            _CANDLE_SCOPE_UNAUTHORIZED_UNTIL_EPOCH = time.time() + _scope_cooldown_seconds()
        raise RevolutCandleFetchError(
            "No supported Revolut candle endpoint available for this runtime/auth scope "
            f"(hint={scope_hint} attempts={len(failures)} sample_failures={'; '.join(failures[:3])})",
            permanent=True,
        )

    raise RevolutCandleFetchError(
        "Failed to fetch Revolut candles after trying endpoint variants",
        permanent=False,
    )
