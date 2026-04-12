from __future__ import annotations

import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Any

from data.revolut_incremental_sync import sync_new_candles
from utils.state_paths import resolve_state_file


DEFAULT_TIMEFRAMES = ["1h", "4h", "1d"]
DEFAULT_DECISION_TIMEFRAME = "1m"
CORE_TIMEFRAME_PRIORITY = {"1h": 0, "4h": 1, "1d": 2}
DEFAULT_CADENCE_SECONDS = {
    "1m": 20,
    "5m": 60,
    "15m": 180,
    "1h": 420,
    "4h": 1200,
    "1d": 2700,
}
DEFAULT_RESERVED_REQUESTS_DECISION_TIMEFRAME = 3
DEFAULT_MAX_BACKGROUND_SHARE = 0.5
DEFAULT_SYNC_AUTO_SCALE_REQUESTS_ENABLED = False
DEFAULT_SYNC_AUTO_SCALE_REQUESTS_MAX_PER_TICK = 12
DEFAULT_SYNC_TARGET_DECISION_FRESHNESS_SECONDS = 90.0
DEFAULT_SYNC_MIN_BACKGROUND_JOBS_PER_TICK = 1
DEFAULT_SYNC_ASSUMED_TICK_SECONDS = 12.0
DEFAULT_STALE_CATCHUP_ENABLED = True
DEFAULT_STALE_CATCHUP_AGE_INTERVALS = 6
DEFAULT_STALE_CATCHUP_RESERVED_REQUESTS = 2
DEFAULT_STALE_CATCHUP_MAX_SYMBOLS = 8
DEFAULT_WATERMARK_PERSIST_ENABLED = True
DEFAULT_WATERMARK_TTL_SECONDS = 6 * 60 * 60
DEFAULT_WATERMARK_PERSIST_INTERVAL_SECONDS = 30
DEFAULT_WATERMARK_MAX_ENTRIES = 5000
DEFAULT_STATE_DIR = Path(__file__).resolve().parent.parent / "state"
SCHEDULER_WATERMARK_PATH = resolve_state_file(DEFAULT_STATE_DIR, "scheduler_sync_watermark.json")

_last_sync_at: dict[tuple[str, str], float] = {}
_sync_job_stats: dict[tuple[str, str], dict[str, Any]] = {}
_watermark_loaded = False
_last_watermark_persist_epoch = 0.0
_background_timeframe_rr_index = 0
_last_tick_epoch: float | None = None


def _to_int(value: Any, fallback: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def _to_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _to_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return fallback


def _safe_int(value: Any, fallback: int, min_value: int = 0) -> int:
    parsed = _to_int(value, fallback)
    return max(int(parsed), int(min_value))


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
        value = list(DEFAULT_TIMEFRAMES)
    out: list[str] = []
    for row in value:
        tf = str(row).strip().lower()
        if tf and tf not in out:
            out.append(tf)
    if not out:
        out = list(DEFAULT_TIMEFRAMES)
    decision_tf = _decision_timeframe(cfg)
    if decision_tf not in out:
        out.append(decision_tf)
    return out


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


def _auto_scale_requests_enabled(cfg: dict[str, Any]) -> bool:
    return _to_bool(
        _market_data_cfg(cfg).get(
            "sync_auto_scale_requests_enabled",
            DEFAULT_SYNC_AUTO_SCALE_REQUESTS_ENABLED,
        ),
        DEFAULT_SYNC_AUTO_SCALE_REQUESTS_ENABLED,
    )


def _auto_scale_requests_max_per_tick(cfg: dict[str, Any], base_cap: int) -> int:
    return max(
        int(base_cap),
        _safe_int(
            _market_data_cfg(cfg).get(
                "sync_auto_scale_requests_max_per_tick",
                DEFAULT_SYNC_AUTO_SCALE_REQUESTS_MAX_PER_TICK,
            ),
            DEFAULT_SYNC_AUTO_SCALE_REQUESTS_MAX_PER_TICK,
            min_value=1,
        ),
    )


def _target_decision_freshness_seconds(cfg: dict[str, Any]) -> float:
    return max(
        15.0,
        _to_float(
            _market_data_cfg(cfg).get(
                "sync_target_decision_freshness_seconds",
                DEFAULT_SYNC_TARGET_DECISION_FRESHNESS_SECONDS,
            ),
            DEFAULT_SYNC_TARGET_DECISION_FRESHNESS_SECONDS,
        ),
    )


def _min_background_jobs_per_tick(cfg: dict[str, Any]) -> int:
    return _safe_int(
        _market_data_cfg(cfg).get(
            "sync_min_background_jobs_per_tick",
            DEFAULT_SYNC_MIN_BACKGROUND_JOBS_PER_TICK,
        ),
        DEFAULT_SYNC_MIN_BACKGROUND_JOBS_PER_TICK,
        min_value=0,
    )


def _assumed_tick_seconds(cfg: dict[str, Any]) -> float:
    return max(
        0.5,
        _to_float(
            _market_data_cfg(cfg).get("sync_assumed_tick_seconds", DEFAULT_SYNC_ASSUMED_TICK_SECONDS),
            DEFAULT_SYNC_ASSUMED_TICK_SECONDS,
        ),
    )


def _resolve_tick_interval_seconds(cfg: dict[str, Any], *, now_epoch: float) -> float:
    global _last_tick_epoch
    fallback = _assumed_tick_seconds(cfg)
    last = _last_tick_epoch
    _last_tick_epoch = float(now_epoch)
    if last is None:
        return float(fallback)
    interval = float(now_epoch) - float(last)
    if interval <= 0:
        return float(fallback)
    return max(0.5, interval)


def _decision_timeframe(cfg: dict[str, Any]) -> str:
    tf = str(_market_data_cfg(cfg).get("decision_candle_timeframe", DEFAULT_DECISION_TIMEFRAME) or "").strip().lower()
    return tf or DEFAULT_DECISION_TIMEFRAME


def _reserved_requests_decision_timeframe(cfg: dict[str, Any], request_cap: int) -> int:
    raw = _market_data_cfg(cfg).get(
        "sync_reserved_requests_decision_timeframe",
        DEFAULT_RESERVED_REQUESTS_DECISION_TIMEFRAME,
    )
    return max(0, min(request_cap, _to_int(raw, DEFAULT_RESERVED_REQUESTS_DECISION_TIMEFRAME)))


def _max_background_share(cfg: dict[str, Any]) -> float:
    raw = _market_data_cfg(cfg).get("sync_max_background_share", DEFAULT_MAX_BACKGROUND_SHARE)
    share = _to_float(raw, DEFAULT_MAX_BACKGROUND_SHARE)
    return max(0.0, min(share, 1.0))


def _stale_catchup_enabled(cfg: dict[str, Any]) -> bool:
    return _to_bool(
        _market_data_cfg(cfg).get("sync_stale_catchup_enabled", DEFAULT_STALE_CATCHUP_ENABLED),
        DEFAULT_STALE_CATCHUP_ENABLED,
    )


def _stale_catchup_age_intervals(cfg: dict[str, Any]) -> int:
    return max(
        1,
        _to_int(
            _market_data_cfg(cfg).get(
                "sync_stale_catchup_age_intervals",
                DEFAULT_STALE_CATCHUP_AGE_INTERVALS,
            ),
            DEFAULT_STALE_CATCHUP_AGE_INTERVALS,
        ),
    )


def _stale_catchup_reserved_requests(cfg: dict[str, Any], request_cap: int) -> int:
    raw = _market_data_cfg(cfg).get(
        "sync_stale_catchup_reserved_requests",
        DEFAULT_STALE_CATCHUP_RESERVED_REQUESTS,
    )
    return max(0, min(request_cap, _to_int(raw, DEFAULT_STALE_CATCHUP_RESERVED_REQUESTS)))


def _stale_catchup_max_symbols(cfg: dict[str, Any]) -> int:
    return max(
        1,
        _to_int(
            _market_data_cfg(cfg).get(
                "sync_stale_catchup_max_symbols",
                DEFAULT_STALE_CATCHUP_MAX_SYMBOLS,
            ),
            DEFAULT_STALE_CATCHUP_MAX_SYMBOLS,
        ),
    )


def _watermark_enabled(cfg: dict[str, Any]) -> bool:
    return _to_bool(
        _market_data_cfg(cfg).get("sync_persist_watermark_enabled", DEFAULT_WATERMARK_PERSIST_ENABLED),
        DEFAULT_WATERMARK_PERSIST_ENABLED,
    )


def _watermark_ttl_seconds(cfg: dict[str, Any]) -> int:
    return _safe_int(
        _market_data_cfg(cfg).get("sync_watermark_ttl_seconds", DEFAULT_WATERMARK_TTL_SECONDS),
        DEFAULT_WATERMARK_TTL_SECONDS,
        min_value=60,
    )


def _watermark_persist_interval_seconds(cfg: dict[str, Any]) -> int:
    return _safe_int(
        _market_data_cfg(cfg).get(
            "sync_watermark_persist_interval_seconds",
            DEFAULT_WATERMARK_PERSIST_INTERVAL_SECONDS,
        ),
        DEFAULT_WATERMARK_PERSIST_INTERVAL_SECONDS,
        min_value=1,
    )


def _watermark_max_entries(cfg: dict[str, Any]) -> int:
    return _safe_int(
        _market_data_cfg(cfg).get("sync_watermark_max_entries", DEFAULT_WATERMARK_MAX_ENTRIES),
        DEFAULT_WATERMARK_MAX_ENTRIES,
        min_value=100,
    )


def _load_watermark_if_needed(cfg: dict[str, Any], *, now_epoch: float) -> int:
    global _watermark_loaded
    if _watermark_loaded:
        return 0
    _watermark_loaded = True
    if not _watermark_enabled(cfg):
        return 0
    ttl_seconds = _watermark_ttl_seconds(cfg)
    if not SCHEDULER_WATERMARK_PATH.exists():
        return 0
    try:
        raw = json.loads(SCHEDULER_WATERMARK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(raw, dict):
        return 0
    entries = raw.get("entries", [])
    if not isinstance(entries, list):
        return 0
    restored = 0
    for row in entries:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        timeframe = str(row.get("timeframe") or "").strip().lower()
        last_sync_at = _to_float(row.get("last_sync_at"), None)
        if not symbol or not timeframe or last_sync_at is None:
            continue
        age = max(0.0, float(now_epoch) - float(last_sync_at))
        if age > float(ttl_seconds):
            continue
        _last_sync_at[(symbol, timeframe)] = float(last_sync_at)
        restored += 1
    return restored


def _persist_watermark_if_due(cfg: dict[str, Any], *, now_epoch: float) -> bool:
    global _last_watermark_persist_epoch
    if not _watermark_enabled(cfg):
        return False
    interval_seconds = _watermark_persist_interval_seconds(cfg)
    if (float(now_epoch) - float(_last_watermark_persist_epoch)) < float(interval_seconds):
        return False
    max_entries = _watermark_max_entries(cfg)
    entries = sorted(
        (
            {
                "symbol": str(symbol),
                "timeframe": str(timeframe),
                "last_sync_at": float(last_sync_at),
            }
            for (symbol, timeframe), last_sync_at in _last_sync_at.items()
        ),
        key=lambda row: float(row.get("last_sync_at", 0.0)),
        reverse=True,
    )[:max_entries]
    payload = {"updated_at_epoch": float(now_epoch), "entries": entries}
    tmp_path = SCHEDULER_WATERMARK_PATH.with_suffix(".tmp")
    try:
        SCHEDULER_WATERMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=True), encoding="utf-8")
        tmp_path.replace(SCHEDULER_WATERMARK_PATH)
        _last_watermark_persist_epoch = float(now_epoch)
        return True
    except Exception:
        return False


def _max_jobs_for_share(request_cap: int, share: float) -> int:
    share = max(0.0, min(float(share), 1.0))
    if share <= 0:
        return 0
    jobs = int(request_cap * share)
    if jobs <= 0:
        jobs = 1
    return min(max(jobs, 0), max(int(request_cap), 0))


def _timeframe_share_caps(cfg: dict[str, Any], request_cap: int) -> dict[str, int]:
    market_data_cfg = _market_data_cfg(cfg)
    raw = market_data_cfg.get("sync_timeframe_max_share", {})
    if not isinstance(raw, dict):
        return {}
    caps: dict[str, int] = {}
    for key, value in raw.items():
        tf = str(key or "").strip().lower()
        if not tf:
            continue
        cap_jobs = _max_jobs_for_share(request_cap, _to_float(value, 1.0))
        caps[tf] = max(0, cap_jobs)
    return caps


def _background_timeframe_order(
    *,
    due_by_timeframe: Counter[str],
    decision_timeframe: str,
) -> list[str]:
    decision_tf = str(decision_timeframe or "").strip().lower()
    core_order = ["1h", "4h", "1d"]
    secondary_order = ["5m", "15m", "30m"]
    present = [
        tf
        for tf, count in due_by_timeframe.items()
        if tf and tf != decision_tf and int(count) > 0
    ]
    ordered: list[str] = []
    for tf in core_order + secondary_order:
        if tf in present and tf not in ordered:
            ordered.append(tf)
    for tf in sorted(present):
        if tf not in ordered:
            ordered.append(tf)
    return ordered


def _error_backoff_seconds(cfg: dict[str, Any]) -> int:
    return max(1, _to_int(_market_data_cfg(cfg).get("sync_error_backoff_seconds", 60), 60))


def _resolve_candle_fallback_policy(
    cfg: dict[str, Any],
    *,
    timeframe: str,
    decision_timeframe: str,
) -> tuple[bool | None, bool | None]:
    market_data_cfg = _market_data_cfg(cfg)
    source_map = market_data_cfg.get("source_map", {})
    if not isinstance(source_map, dict):
        return None, None
    candles = source_map.get("candles", {})
    if not isinstance(candles, dict):
        return None, None

    def _opt_bool(key: str) -> bool | None:
        if key not in candles:
            return None
        return bool(candles.get(key))

    base_public = _opt_bool("allow_public_fallback")
    base_snapshot = _opt_bool("allow_snapshot_fallback")
    if str(timeframe).strip().lower() == str(decision_timeframe).strip().lower():
        decision_public = _opt_bool("decision_use_public_fallback")
        decision_snapshot = _opt_bool("decision_use_snapshot_fallback")
        return (
            decision_public if decision_public is not None else base_public,
            decision_snapshot if decision_snapshot is not None else base_snapshot,
        )
    return base_public, base_snapshot


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
    global _background_timeframe_rr_index
    if not _enabled(cfg):
        return {"enabled": False, "requests": 0, "inserted": 0, "errors": 0, "jobs": []}

    now = float(now_epoch if now_epoch is not None else time.time())
    tick_interval_seconds = _resolve_tick_interval_seconds(cfg, now_epoch=now)
    watermark_restored = _load_watermark_if_needed(cfg, now_epoch=now)
    timeframes = _timeframes(cfg)
    cadence = _cadence_map(cfg)
    request_cap_base = _max_requests(cfg)
    decision_timeframe = _decision_timeframe(cfg)
    auto_scale_enabled = _auto_scale_requests_enabled(cfg)
    target_decision_freshness_seconds = _target_decision_freshness_seconds(cfg)
    has_background_timeframes = any(
        str(tf or "").strip().lower() != decision_timeframe for tf in timeframes
    )
    min_background_jobs = _min_background_jobs_per_tick(cfg) if has_background_timeframes else 0
    auto_scale_max_cap = _auto_scale_requests_max_per_tick(cfg, request_cap_base)
    decision_jobs_required = 0
    if auto_scale_enabled and symbols:
        decision_jobs_required = max(
            1,
            int(
                math.ceil(
                    (len({str(s or "").strip().upper() for s in symbols if str(s or "").strip()}) * tick_interval_seconds)
                    / target_decision_freshness_seconds
                )
            ),
        )
    desired_request_cap = request_cap_base
    if auto_scale_enabled and decision_jobs_required > 0:
        desired_request_cap = max(
            int(request_cap_base),
            int(decision_jobs_required + min_background_jobs),
        )
    request_cap = min(int(auto_scale_max_cap), int(desired_request_cap))
    reserved_decision_requests = _reserved_requests_decision_timeframe(cfg, request_cap)
    if auto_scale_enabled and decision_jobs_required > 0:
        auto_reserved = min(int(request_cap), int(decision_jobs_required))
        if min_background_jobs > 0 and request_cap > min_background_jobs:
            auto_reserved = min(auto_reserved, int(request_cap - min_background_jobs))
        reserved_decision_requests = max(int(reserved_decision_requests), int(auto_reserved))
    stale_catchup_enabled = _stale_catchup_enabled(cfg)
    stale_catchup_age_intervals = _stale_catchup_age_intervals(cfg)
    stale_catchup_reserved_requests = _stale_catchup_reserved_requests(cfg, request_cap)
    stale_catchup_max_symbols = _stale_catchup_max_symbols(cfg)
    background_share = _max_background_share(cfg)
    timeframe_share_caps = _timeframe_share_caps(cfg, request_cap)
    error_backoff_seconds = _error_backoff_seconds(cfg)

    jobs: list[dict[str, Any]] = []
    attempted_jobs = 0
    requests = 0
    inserted = 0
    new_inserted = 0
    updated_existing = 0
    candidate_new = 0
    eligible_closed = 0
    skipped_existing = 0
    skipped_partial = 0
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

    due_jobs: list[dict[str, Any]] = []
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
            age_seconds = max(0.0, now - sort_last) if last is not None else float(cadence_seconds)
            due_jobs.append(
                {
                    "sort_last": sort_last,
                    "tf_priority": tf_priority,
                    "tie_break": tie_break,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "cadence_seconds": cadence_seconds,
                    "age_seconds": age_seconds,
                }
            )

    due_jobs.sort(
        key=lambda row: (
            row.get("sort_last", 0.0),
            row.get("tf_priority", 9),
            row.get("tie_break", 0),
            row.get("symbol", ""),
            row.get("timeframe", ""),
        )
    )

    due_by_timeframe = Counter(str(row.get("timeframe") or "").strip().lower() for row in due_jobs)
    oldest_due_age_by_timeframe: dict[str, float] = {}
    for row in due_jobs:
        tf = str(row.get("timeframe") or "").strip().lower()
        age = float(row.get("age_seconds", 0.0) or 0.0)
        prev = oldest_due_age_by_timeframe.get(tf, 0.0)
        if age > prev:
            oldest_due_age_by_timeframe[tf] = age

    selected_jobs: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str]] = set()
    selected_by_timeframe: Counter[str] = Counter()
    selected_background_jobs = 0
    stale_catchup_candidate_symbols: list[str] = []
    stale_catchup_selected_jobs = 0
    decision_due_jobs = [row for row in due_jobs if row.get("timeframe") == decision_timeframe]
    decision_due_count = len(decision_due_jobs)
    background_due_timeframes = [
        str(tf or "").strip().lower()
        for tf, count in due_by_timeframe.items()
        if str(tf or "").strip().lower() != decision_timeframe and int(count or 0) > 0
    ]
    background_due_count = sum(int(due_by_timeframe.get(tf, 0) or 0) for tf in background_due_timeframes)
    background_degraded = False
    for tf in background_due_timeframes:
        oldest_due_age = float(oldest_due_age_by_timeframe.get(tf, 0.0) or 0.0)
        cadence_seconds = max(1, int(cadence.get(tf, 60)))
        if oldest_due_age > float(cadence_seconds * 3):
            background_degraded = True
            break
    required_background_jobs = 0
    if background_due_count > 0 and request_cap > 1:
        required_background_jobs = min(
            max(int(min_background_jobs), 0),
            max(int(request_cap) - 1, 0),
        )
        if background_degraded:
            required_background_jobs = max(required_background_jobs, 1)
        required_background_jobs = min(required_background_jobs, int(background_due_count))

    max_decision_slots = max(int(request_cap) - int(required_background_jobs), 0)
    if decision_due_count > 0:
        max_decision_slots = max(max_decision_slots, 1)
        max_decision_slots = min(max_decision_slots, int(request_cap))

    reserved_target = min(max(reserved_decision_requests, 0), decision_due_count, request_cap)
    if max_decision_slots >= 0:
        reserved_target = min(reserved_target, max_decision_slots)
    for row in decision_due_jobs[:reserved_target]:
        key = (str(row.get("symbol")), str(row.get("timeframe")))
        selected_jobs.append(row)
        selected_keys.add(key)
        selected_by_timeframe[str(row.get("timeframe"))] += 1

    stale_catchup_decision_slots_remaining = max(int(max_decision_slots) - int(reserved_target), 0)
    if stale_catchup_enabled and stale_catchup_reserved_requests > 0 and stale_catchup_max_symbols > 0:
        stale_candidates: list[dict[str, Any]] = []
        seen_candidate_symbols: set[str] = set()
        for row in decision_due_jobs:
            key = (str(row.get("symbol")), str(row.get("timeframe")))
            if key in selected_keys:
                continue
            cadence_seconds = max(1, int(row.get("cadence_seconds", 60) or 60))
            age_seconds = max(0.0, float(row.get("age_seconds", 0.0) or 0.0))
            if age_seconds < (cadence_seconds * stale_catchup_age_intervals):
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            if symbol not in seen_candidate_symbols:
                seen_candidate_symbols.add(symbol)
                stale_catchup_candidate_symbols.append(symbol)
            stale_candidates.append(row)
        stale_candidates.sort(
            key=lambda row: (
                -float(row.get("age_seconds", 0.0) or 0.0),
                str(row.get("symbol") or ""),
            )
        )
        symbol_slots_used: set[str] = set()
        for row in stale_candidates:
            if len(selected_jobs) >= request_cap:
                break
            if stale_catchup_selected_jobs >= stale_catchup_reserved_requests:
                break
            if stale_catchup_selected_jobs >= stale_catchup_decision_slots_remaining:
                break
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            if symbol in symbol_slots_used:
                continue
            if len(symbol_slots_used) >= stale_catchup_max_symbols:
                break
            tf = str(row.get("timeframe") or "").strip().lower()
            tf_cap_jobs = timeframe_share_caps.get(tf)
            if tf_cap_jobs is not None and selected_by_timeframe.get(tf, 0) >= int(tf_cap_jobs):
                continue
            key = (symbol, tf)
            if key in selected_keys:
                continue
            selected_jobs.append(row)
            selected_keys.add(key)
            selected_by_timeframe[tf] += 1
            symbol_slots_used.add(symbol)
            stale_catchup_selected_jobs += 1

    remaining_jobs = [
        row
        for row in due_jobs
        if (str(row.get("symbol")), str(row.get("timeframe"))) not in selected_keys
    ]
    background_timeframe_order = _background_timeframe_order(
        due_by_timeframe=due_by_timeframe,
        decision_timeframe=decision_timeframe,
    )
    max_background_jobs = (
        _max_jobs_for_share(request_cap, background_share) if decision_due_count > 0 else request_cap
    )
    max_background_jobs = min(max(int(max_background_jobs), int(required_background_jobs)), int(request_cap))
    while len(selected_jobs) < request_cap and remaining_jobs:
        picked_idx: int | None = None
        preferred_background_tf: str | None = None
        force_background_pick = (
            bool(background_timeframe_order)
            and int(selected_background_jobs) < int(required_background_jobs)
        )
        if force_background_pick:
            preferred_background_tf = background_timeframe_order[
                _background_timeframe_rr_index % len(background_timeframe_order)
            ]
            for idx, row in enumerate(remaining_jobs):
                tf = str(row.get("timeframe") or "").strip().lower()
                if tf != preferred_background_tf:
                    continue
                tf_cap_jobs = timeframe_share_caps.get(tf)
                if tf_cap_jobs is not None and selected_by_timeframe.get(tf, 0) >= int(tf_cap_jobs):
                    continue
                picked_idx = idx
                break
        if (
            picked_idx is None
            and
            decision_due_count > 0
            and selected_background_jobs < max_background_jobs
            and background_timeframe_order
        ):
            preferred_background_tf = background_timeframe_order[
                _background_timeframe_rr_index % len(background_timeframe_order)
            ]
            for idx, row in enumerate(remaining_jobs):
                tf = str(row.get("timeframe") or "").strip().lower()
                if tf != preferred_background_tf:
                    continue
                tf_cap_jobs = timeframe_share_caps.get(tf)
                if tf_cap_jobs is not None and selected_by_timeframe.get(tf, 0) >= int(tf_cap_jobs):
                    continue
                if tf != decision_timeframe and selected_background_jobs >= max_background_jobs:
                    continue
                picked_idx = idx
                break
        if picked_idx is None:
            for idx, row in enumerate(remaining_jobs):
                tf = str(row.get("timeframe") or "").strip().lower()
                if force_background_pick and tf == decision_timeframe:
                    continue
                tf_cap_jobs = timeframe_share_caps.get(tf)
                if tf_cap_jobs is not None and selected_by_timeframe.get(tf, 0) >= int(tf_cap_jobs):
                    continue
                if tf != decision_timeframe and decision_due_count > 0 and selected_background_jobs >= max_background_jobs:
                    continue
                picked_idx = idx
                break
        if picked_idx is None:
            break
        row = remaining_jobs.pop(picked_idx)
        selected_jobs.append(row)
        tf = str(row.get("timeframe") or "").strip().lower()
        selected_by_timeframe[tf] += 1
        if tf != decision_timeframe:
            selected_background_jobs += 1
            if background_timeframe_order:
                _background_timeframe_rr_index += 1

    skipped_due_by_timeframe: dict[str, int] = {}
    starvation_timeframes: list[str] = []
    for tf, due_count in due_by_timeframe.items():
        selected_count = int(selected_by_timeframe.get(tf, 0))
        skipped = max(int(due_count) - selected_count, 0)
        skipped_due_by_timeframe[tf] = skipped
        if due_count > 0 and selected_count == 0:
            starvation_timeframes.append(tf)

    decision_selected_count = int(selected_by_timeframe.get(decision_timeframe, 0))
    decision_reservation_met = decision_selected_count >= reserved_target
    decision_required_for_guard = max(int(reserved_target), 0)
    if decision_due_count > 0 and auto_scale_enabled and decision_jobs_required > 0:
        decision_required_for_guard = max(
            int(decision_required_for_guard),
            int(min(decision_due_count, decision_jobs_required)),
        )
    decision_oldest_due_age = float(oldest_due_age_by_timeframe.get(decision_timeframe, 0.0) or 0.0)
    ingestion_guard_reasons: list[str] = []
    if decision_due_count > 0 and decision_selected_count <= 0:
        ingestion_guard_reasons.append("decision_timeframe_starved")
    if decision_required_for_guard > 0 and decision_selected_count < decision_required_for_guard:
        ingestion_guard_reasons.append("decision_timeframe_under_served")
    if decision_due_count > 0 and decision_oldest_due_age > (target_decision_freshness_seconds * 1.5):
        ingestion_guard_reasons.append("decision_oldest_due_exceeds_target")
    ingestion_guard_status = "DEGRADED" if ingestion_guard_reasons else "OK"

    for row in selected_jobs:
        symbol = str(row.get("symbol"))
        timeframe = str(row.get("timeframe"))
        cadence_seconds = int(row.get("cadence_seconds", cadence.get(timeframe, 60)) or cadence.get(timeframe, 60))
        key = (symbol, timeframe)
        attempted_jobs += 1
        next_delay_seconds = cadence_seconds
        allow_public_fallback, allow_snapshot_fallback = _resolve_candle_fallback_policy(
            cfg,
            timeframe=timeframe,
            decision_timeframe=decision_timeframe,
        )
        try:
            try:
                result = sync_new_candles(
                    symbol=symbol,
                    timeframe=timeframe,
                    include_partial=False,
                    cfg=cfg,
                    allow_public_fallback=allow_public_fallback,
                    allow_snapshot_fallback=allow_snapshot_fallback,
                )
            except TypeError:
                # Backward-compatible path for test doubles/legacy sync fns that
                # do not support fallback override kwargs yet.
                result = sync_new_candles(
                    symbol=symbol,
                    timeframe=timeframe,
                    include_partial=False,
                    cfg=cfg,
                )
            result_status = str(result.get("status", "ok")).strip().lower()
            metric_key = (symbol, timeframe)
            stat = _sync_job_stats.get(metric_key, {})
            stat["attempts"] = int(stat.get("attempts", 0) or 0) + 1
            stat["last_attempt_at_epoch"] = float(now)
            requests += int(result.get("requests", 0) or 0)
            inserted += int(result.get("inserted", 0) or 0)
            new_inserted += int(result.get("new_inserted", 0) or 0)
            updated_existing += int(result.get("updated_existing", 0) or 0)
            candidate_new += int(result.get("candidate_new", 0) or 0)
            eligible_closed += int(result.get("eligible_closed", 0) or 0)
            skipped_existing += int(result.get("skipped_existing", 0) or 0)
            skipped_partial += int(result.get("skipped_partial", 0) or 0)
            if result_status in {"degraded", "unsupported"}:
                degraded += 1
            else:
                previous_success_at = stat.get("last_success_at_epoch")
                stat["successes"] = int(stat.get("successes", 0) or 0) + 1
                stat["last_success_at_epoch"] = float(now)
                if previous_success_at is not None:
                    interval = max(0.0, float(now) - float(previous_success_at))
                    prev_ema = stat.get("ema_success_interval_seconds")
                    stat["ema_success_interval_seconds"] = (
                        float(interval)
                        if prev_ema is None
                        else ((float(prev_ema) * 0.8) + (float(interval) * 0.2))
                    )
            stat["last_status"] = result_status or "ok"
            latest_open_time = result.get("latest_open_time")
            if latest_open_time is not None:
                stat["latest_open_time_ms"] = int(latest_open_time)
            _sync_job_stats[metric_key] = stat
            jobs.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "status": result_status or "ok",
                    "fetched": int(result.get("fetched", 0) or 0),
                    "inserted": int(result.get("inserted", 0) or 0),
                    "new_inserted": int(result.get("new_inserted", 0) or 0),
                    "updated_existing": int(result.get("updated_existing", 0) or 0),
                    "candidate_new": int(result.get("candidate_new", 0) or 0),
                    "eligible_closed": int(result.get("eligible_closed", 0) or 0),
                    "skipped_existing": int(result.get("skipped_existing", 0) or 0),
                    "skipped_partial": int(result.get("skipped_partial", 0) or 0),
                    "source": result.get("source"),
                    "note": result.get("note"),
                }
            )
        except Exception as exc:
            errors += 1
            next_delay_seconds = min(cadence_seconds, error_backoff_seconds)
            metric_key = (symbol, timeframe)
            stat = _sync_job_stats.get(metric_key, {})
            stat["attempts"] = int(stat.get("attempts", 0) or 0) + 1
            stat["errors"] = int(stat.get("errors", 0) or 0) + 1
            stat["last_attempt_at_epoch"] = float(now)
            stat["last_error_at_epoch"] = float(now)
            stat["last_status"] = "error"
            stat["last_error"] = str(exc)
            _sync_job_stats[metric_key] = stat
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

    decision_metrics_rows: list[dict[str, Any]] = []
    decision_metric_stale_symbols: list[str] = []
    for symbol in unique_symbols:
        key = (symbol, decision_timeframe)
        last_sync_at = _last_sync_at.get(key)
        age_seconds = (
            max(0.0, float(now) - float(last_sync_at))
            if last_sync_at is not None
            else None
        )
        stat = _sync_job_stats.get(key, {})
        observed_interval = stat.get("ema_success_interval_seconds")
        update_frequency_per_hour = None
        if observed_interval is not None and float(observed_interval) > 0:
            update_frequency_per_hour = 3600.0 / float(observed_interval)
        elif age_seconds is not None and age_seconds > 0:
            update_frequency_per_hour = 3600.0 / float(age_seconds)
        stale = bool(
            age_seconds is not None and age_seconds > float(target_decision_freshness_seconds)
        )
        if stale:
            decision_metric_stale_symbols.append(symbol)
        decision_metrics_rows.append(
            {
                "symbol": symbol,
                "timeframe": decision_timeframe,
                "last_sync_at_epoch": (float(last_sync_at) if last_sync_at is not None else None),
                "age_seconds": (float(age_seconds) if age_seconds is not None else None),
                "observed_update_interval_seconds": (
                    float(observed_interval) if observed_interval is not None else None
                ),
                "update_frequency_per_hour": (
                    float(update_frequency_per_hour) if update_frequency_per_hour is not None else None
                ),
                "target_freshness_seconds": float(target_decision_freshness_seconds),
                "stale": stale,
                "attempts": int(stat.get("attempts", 0) or 0),
                "successes": int(stat.get("successes", 0) or 0),
                "errors": int(stat.get("errors", 0) or 0),
                "last_status": stat.get("last_status"),
            }
        )

    watermark_persisted = _persist_watermark_if_due(cfg, now_epoch=now)

    return {
        "enabled": True,
        "attempted_jobs": attempted_jobs,
        "requests": requests,
        "inserted": inserted,
        "new_inserted": new_inserted,
        "updated_existing": updated_existing,
        "candidate_new": candidate_new,
        "eligible_closed": eligible_closed,
        "skipped_existing": skipped_existing,
        "skipped_partial": skipped_partial,
        "errors": errors,
        "degraded": degraded,
        "scheduler": {
            "request_cap": int(request_cap),
            "request_cap_base": int(request_cap_base),
            "request_cap_auto_scale_enabled": bool(auto_scale_enabled),
            "request_cap_auto_scale_max": int(auto_scale_max_cap),
            "request_cap_desired": int(desired_request_cap),
            "tick_interval_seconds": float(tick_interval_seconds),
            "target_decision_freshness_seconds": float(target_decision_freshness_seconds),
            "decision_jobs_required_for_target": int(decision_jobs_required),
            "min_background_jobs_per_tick": int(min_background_jobs),
            "decision_timeframe": decision_timeframe,
            "reserved_requests_decision_timeframe": int(reserved_decision_requests),
            "decision_due_jobs": int(decision_due_count),
            "background_due_jobs": int(background_due_count),
            "background_degraded": bool(background_degraded),
            "required_background_jobs": int(required_background_jobs),
            "decision_selected_jobs": int(decision_selected_count),
            "decision_reservation_met": bool(decision_reservation_met),
            "decision_required_jobs_for_guard": int(decision_required_for_guard),
            "max_decision_slots": int(max_decision_slots),
            "decision_reserved_target": int(reserved_target),
            "decision_reserved_slots_total": int(reserved_target + stale_catchup_selected_jobs),
            "decision_oldest_due_age_seconds": float(decision_oldest_due_age),
            "ingestion_guard": {
                "status": ingestion_guard_status,
                "reasons": list(dict.fromkeys(ingestion_guard_reasons)),
                "decision_required_jobs": int(decision_required_for_guard),
                "decision_selected_jobs": int(decision_selected_count),
                "decision_due_jobs": int(decision_due_count),
                "decision_oldest_due_age_seconds": float(decision_oldest_due_age),
                "target_decision_freshness_seconds": float(target_decision_freshness_seconds),
            },
            "stale_catchup_enabled": bool(stale_catchup_enabled),
            "stale_catchup_age_intervals": int(stale_catchup_age_intervals),
            "stale_catchup_reserved_requests": int(stale_catchup_reserved_requests),
            "stale_catchup_max_symbols": int(stale_catchup_max_symbols),
            "stale_catchup_candidate_symbols": list(stale_catchup_candidate_symbols),
            "stale_catchup_selected_jobs": int(stale_catchup_selected_jobs),
            "max_background_share": float(background_share),
            "max_background_jobs": int(max_background_jobs),
            "selected_background_jobs": int(selected_background_jobs),
            "background_timeframe_order": list(background_timeframe_order),
            "background_timeframe_rr_index": int(_background_timeframe_rr_index),
            "due_jobs_total": int(len(due_jobs)),
            "selected_jobs_total": int(len(selected_jobs)),
            "due_jobs_by_timeframe": dict(due_by_timeframe),
            "selected_jobs_by_timeframe": dict(selected_by_timeframe),
            "skipped_due_jobs_by_timeframe": skipped_due_by_timeframe,
            "oldest_due_age_seconds_by_timeframe": {
                k: float(v) for k, v in oldest_due_age_by_timeframe.items()
            },
            "starvation_timeframes": sorted(starvation_timeframes),
            "timeframe_share_caps_jobs": {
                k: int(v) for k, v in timeframe_share_caps.items()
            },
            "watermark_restore_entries": int(watermark_restored),
            "watermark_persisted": bool(watermark_persisted),
            "decision_timeframe_metrics": {
                "symbols_total": int(len(unique_symbols)),
                "stale_symbols": list(decision_metric_stale_symbols),
                "rows": decision_metrics_rows,
            },
        },
        "jobs": jobs,
    }
