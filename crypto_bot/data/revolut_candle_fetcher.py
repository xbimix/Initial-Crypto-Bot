from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

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
_ENDPOINT_CAPABILITY_CACHE: dict[str, dict[str, Any]] = {}
_CANDLE_TELEMETRY: dict[str, Any] = {
    "fetch_calls": 0,
    "success_calls": 0,
    "failed_calls": 0,
    "official_success_calls": 0,
    "public_success_calls": 0,
    "candidate_success": {},
    "candidate_failures": {},
}


def _scope_cooldown_seconds() -> float:
    raw = os.getenv("REVBOT_CANDLE_SCOPE_COOLDOWN_SECONDS", "900")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 900.0
    return max(60.0, value)


def _capability_ttl_seconds() -> float:
    raw = os.getenv("REVBOT_CANDLE_CAPABILITY_TTL_SECONDS", "3600")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 3600.0
    return max(60.0, value)


def _allow_public_fallback_default() -> bool:
    return str(os.getenv("REVBOT_CANDLE_ALLOW_PUBLIC_FALLBACK", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _candidate_key(path: str, mode: str, auth: bool) -> str:
    return f"{'auth' if auth else 'public'}:{path}:{mode}"


def _normalize_symbol(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    token = raw.strip().upper()
    if not token:
        return ""
    return token.replace("/", "-").replace("_", "-")


def _symbol_path_variants(symbol: str) -> list[str]:
    canonical = _normalize_symbol(symbol)
    if not canonical:
        return []
    variants: list[str] = [canonical]
    slash_variant = canonical.replace("-", "/")
    if slash_variant not in variants:
        variants.append(slash_variant)
    encoded_slash_variant = quote(slash_variant, safe="")
    if encoded_slash_variant not in variants:
        variants.append(encoded_slash_variant)
    return variants


def _candidate_targets_symbol(path: str, symbol: str) -> bool:
    symbol_norm = _normalize_symbol(symbol)
    if not symbol_norm:
        return False
    return f"/{symbol_norm}" in str(path or "").upper()


def _candidate_is_stale(entry: dict[str, Any], now_epoch: float) -> bool:
    ttl = _capability_ttl_seconds()
    updated = float(entry.get("updated_epoch", 0.0) or 0.0)
    return updated <= 0 or (now_epoch - updated) > ttl


def _candidate_is_blocked(path: str, mode: str, auth: bool, now_epoch: float) -> bool:
    key = _candidate_key(path, mode, auth)
    entry = _ENDPOINT_CAPABILITY_CACHE.get(key)
    if not isinstance(entry, dict) or _candidate_is_stale(entry, now_epoch):
        return False
    status = str(entry.get("status", "")).strip().lower()
    return status in {"unsupported", "auth_unauthorized"}


def _record_candidate_success(path: str, mode: str, auth: bool):
    now_epoch = time.time()
    key = _candidate_key(path, mode, auth)
    entry = _ENDPOINT_CAPABILITY_CACHE.get(key, {})
    success_count = int(entry.get("success_count", 0) or 0) + 1
    _ENDPOINT_CAPABILITY_CACHE[key] = {
        "status": "ok",
        "updated_epoch": now_epoch,
        "success_count": success_count,
        "failure_count": int(entry.get("failure_count", 0) or 0),
        "last_status_code": 200,
    }
    counts = _CANDLE_TELEMETRY.setdefault("candidate_success", {})
    counts[key] = int(counts.get(key, 0) or 0) + 1


def _record_candidate_failure(path: str, mode: str, auth: bool, status_code: int | None):
    now_epoch = time.time()
    key = _candidate_key(path, mode, auth)
    entry = _ENDPOINT_CAPABILITY_CACHE.get(key, {})
    failure_count = int(entry.get("failure_count", 0) or 0) + 1
    status = "retryable"
    if auth and status_code == 401:
        status = "auth_unauthorized"
    elif status_code in {400, 403, 404}:
        status = "unsupported"
    _ENDPOINT_CAPABILITY_CACHE[key] = {
        "status": status,
        "updated_epoch": now_epoch,
        "success_count": int(entry.get("success_count", 0) or 0),
        "failure_count": failure_count,
        "last_status_code": status_code,
    }
    counts = _CANDLE_TELEMETRY.setdefault("candidate_failures", {})
    counts[key] = int(counts.get(key, 0) or 0) + 1


def get_candle_fetch_telemetry() -> dict[str, Any]:
    now_epoch = time.time()
    ttl = _capability_ttl_seconds()
    active_capabilities: dict[str, Any] = {}
    for key, entry in _ENDPOINT_CAPABILITY_CACHE.items():
        if not isinstance(entry, dict):
            continue
        updated = float(entry.get("updated_epoch", 0.0) or 0.0)
        if updated <= 0 or (now_epoch - updated) > ttl:
            continue
        active_capabilities[key] = {
            "status": str(entry.get("status", "unknown")),
            "updated_epoch": updated,
            "success_count": int(entry.get("success_count", 0) or 0),
            "failure_count": int(entry.get("failure_count", 0) or 0),
            "last_status_code": entry.get("last_status_code"),
        }
    return {
        "fetch_calls": int(_CANDLE_TELEMETRY.get("fetch_calls", 0) or 0),
        "success_calls": int(_CANDLE_TELEMETRY.get("success_calls", 0) or 0),
        "failed_calls": int(_CANDLE_TELEMETRY.get("failed_calls", 0) or 0),
        "official_success_calls": int(_CANDLE_TELEMETRY.get("official_success_calls", 0) or 0),
        "public_success_calls": int(_CANDLE_TELEMETRY.get("public_success_calls", 0) or 0),
        "candidate_success": dict(_CANDLE_TELEMETRY.get("candidate_success", {})),
        "candidate_failures": dict(_CANDLE_TELEMETRY.get("candidate_failures", {})),
        "active_capabilities": active_capabilities,
        "capability_ttl_seconds": ttl,
    }


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
    *,
    allow_public_fallback: bool | None = None,
) -> list[dict]:
    global _WORKING_CANDLE_REQUEST
    global _CANDLE_SCOPE_UNAUTHORIZED_UNTIL_EPOCH

    interval = int(interval_minutes)
    normalized_symbol = _normalize_symbol(symbol)
    if not normalized_symbol:
        raise ValueError("symbol cannot be empty")
    symbol_variants = _symbol_path_variants(normalized_symbol)
    _CANDLE_TELEMETRY["fetch_calls"] = int(_CANDLE_TELEMETRY.get("fetch_calls", 0) or 0) + 1
    if interval not in SUPPORTED_INTERVALS_MINUTES:
        raise ValueError(f"Unsupported interval minutes: {interval}")
    if int(until_ms) <= int(since_ms):
        return []

    allow_public = (
        bool(allow_public_fallback)
        if isinstance(allow_public_fallback, bool)
        else _allow_public_fallback_default()
    )
    now_epoch = time.time()
    auth_scope_cooldown_active = _CANDLE_SCOPE_UNAUTHORIZED_UNTIL_EPOCH > now_epoch
    if auth_scope_cooldown_active and not allow_public:
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
        return (
            datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

    params_primary = {
        "symbol": str(normalized_symbol),
        "interval": interval,
        "since": int(since_ms),
        "until": int(until_ms),
    }
    params_seconds = {
        "symbol": str(normalized_symbol),
        "interval": interval,
        "since": int(since_ms // 1000),
        "until": int(until_ms // 1000),
    }
    params_iso = {
        "symbol": str(normalized_symbol),
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
        "symbol": str(normalized_symbol),
        "interval": interval,
        "start": int(since_ms),
        "end": int(until_ms),
    }
    params_start_end_seconds = {
        "symbol": str(normalized_symbol),
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
    auth_candidates: list[dict[str, Any]] = []
    for symbol_variant in symbol_variants:
        auth_candidates.extend(
            [
                # Canonical documented endpoint first.
                {"path": f"/candles/{symbol_variant}", "mode": "symbolless_primary", "auth": True},
                {"path": f"/candles/{symbol_variant}", "mode": "symbolless_seconds", "auth": True},
                {"path": f"/market-data/candles/{symbol_variant}", "mode": "symbolless_primary", "auth": True},
                {"path": f"/market-data/candles/{symbol_variant}", "mode": "symbolless_seconds", "auth": True},
                {"path": f"/market-data/historical-candles/{symbol_variant}", "mode": "symbolless_primary", "auth": True},
                {"path": f"/market-data/historical-candles/{symbol_variant}", "mode": "symbolless_seconds", "auth": True},
                {"path": f"/market-data/{symbol_variant}/candles", "mode": "symbolless_primary", "auth": True},
                {"path": f"/market-data/{symbol_variant}/candles", "mode": "symbolless_seconds", "auth": True},
                {"path": f"/market-data/{symbol_variant}/historical-candles", "mode": "symbolless_primary", "auth": True},
                {"path": f"/market-data/{symbol_variant}/historical-candles", "mode": "symbolless_seconds", "auth": True},
                {"path": f"/historical-candles/{symbol_variant}", "mode": "symbolless_primary", "auth": True},
                {"path": f"/historical-candles/{symbol_variant}", "mode": "symbolless_seconds", "auth": True},
            ]
        )
    auth_candidates.extend(
        [
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
    )
    public_candidates: list[dict[str, Any]] = [
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
    ]
    for symbol_variant in symbol_variants:
        public_candidates.extend(
            [
                {"path": f"/public/market-data/candles/{symbol_variant}", "mode": "symbolless_primary", "auth": False},
                {"path": f"/public/market-data/candles/{symbol_variant}", "mode": "symbolless_seconds", "auth": False},
            ]
        )
    if auth_scope_cooldown_active:
        auth_candidates = []
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
            now_epoch = time.time()
            if _candidate_is_blocked(path, mode, auth, now_epoch):
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
                _WORKING_CANDLE_REQUEST = {
                    "path": path,
                    "mode": mode,
                    "auth": auth,
                    "symbol": normalized_symbol if _candidate_targets_symbol(path, normalized_symbol) else None,
                }
                _record_candidate_success(path, mode, auth)
                _CANDLE_TELEMETRY["success_calls"] = int(_CANDLE_TELEMETRY.get("success_calls", 0) or 0) + 1
                if auth:
                    _CANDLE_TELEMETRY["official_success_calls"] = int(
                        _CANDLE_TELEMETRY.get("official_success_calls", 0) or 0
                    ) + 1
                else:
                    _CANDLE_TELEMETRY["public_success_calls"] = int(
                        _CANDLE_TELEMETRY.get("public_success_calls", 0) or 0
                    ) + 1
                return rows, any_retryable_local, all_not_found_or_unsupported_local, auth_401_local
            except Exception as exc:
                response = getattr(exc, "response", None)
                status_code = getattr(response, "status_code", None)
                failures.append(f"{path} auth={auth} status={status_code} err={exc}")
                _record_candidate_failure(path, mode, auth, status_code)
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
        cached_path = str(_WORKING_CANDLE_REQUEST.get("path") or "")
        cached_symbol = _normalize_symbol(_WORKING_CANDLE_REQUEST.get("symbol"))
        requested_symbol = _normalize_symbol(symbol)
        can_reuse_cached = False
        if cached_symbol and requested_symbol:
            can_reuse_cached = cached_symbol == requested_symbol
        elif not cached_symbol:
            # Generic endpoint candidates are reusable across symbols.
            can_reuse_cached = not _candidate_targets_symbol(cached_path, requested_symbol)
        if can_reuse_cached:
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

    if any_retryable:
        _CANDLE_TELEMETRY["failed_calls"] = int(_CANDLE_TELEMETRY.get("failed_calls", 0) or 0) + 1
        raise RevolutCandleFetchError(
            "Revolut candle endpoint temporarily unavailable; retry later",
            permanent=False,
        )

    if all_not_found_or_unsupported:
        scope_hint = "auth_scope_unauthorized" if auth_401_count > 0 else "not_found_or_unsupported"
        if auth_401_count > 0:
            _CANDLE_SCOPE_UNAUTHORIZED_UNTIL_EPOCH = time.time() + _scope_cooldown_seconds()
        _CANDLE_TELEMETRY["failed_calls"] = int(_CANDLE_TELEMETRY.get("failed_calls", 0) or 0) + 1
        raise RevolutCandleFetchError(
            "No supported Revolut candle endpoint available for this runtime/auth scope "
            f"(hint={scope_hint} attempts={len(failures)} sample_failures={'; '.join(failures[:3])})",
            permanent=True,
        )

    _CANDLE_TELEMETRY["failed_calls"] = int(_CANDLE_TELEMETRY.get("failed_calls", 0) or 0) + 1
    raise RevolutCandleFetchError(
        "Failed to fetch Revolut candles after trying endpoint variants",
        permanent=False,
    )
