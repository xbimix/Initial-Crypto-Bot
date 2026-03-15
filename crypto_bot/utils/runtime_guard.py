from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any


def _parse_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def cleanup_stale_locks(
    state_dir: str | Path,
    *,
    stale_seconds: float | None = None,
) -> dict[str, Any]:
    base = Path(state_dir)
    stale_limit = (
        stale_seconds
        if stale_seconds is not None
        else _parse_float_env("REVBOT_STALE_LOCK_SECONDS", 120.0)
    )
    now = time.time()
    removed: list[str] = []
    scanned = 0

    for path in base.glob("*.lock"):
        scanned += 1
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        if age <= stale_limit:
            continue
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            continue

    return {
        "scanned": scanned,
        "removed_count": len(removed),
        "removed": removed,
        "stale_seconds": stale_limit,
    }


def cleanup_temp_files(
    state_dir: str | Path,
    *,
    older_than_seconds: float | None = None,
) -> dict[str, Any]:
    base = Path(state_dir)
    threshold = (
        older_than_seconds
        if older_than_seconds is not None
        else _parse_float_env("REVBOT_TEMP_FILE_MAX_AGE_SECONDS", 86400.0)
    )
    now = time.time()
    removed: list[str] = []
    scanned = 0

    patterns = (".*.tmp", "*.tmp")
    seen: set[Path] = set()
    for pattern in patterns:
        for path in base.glob(pattern):
            if path in seen:
                continue
            seen.add(path)
            scanned += 1
            try:
                age = now - path.stat().st_mtime
            except OSError:
                continue
            if age <= threshold:
                continue
            try:
                path.unlink()
                removed.append(path.name)
            except OSError:
                continue

    return {
        "scanned": scanned,
        "removed_count": len(removed),
        "removed": removed,
        "older_than_seconds": threshold,
    }


def check_disk_space(
    state_dir: str | Path,
    *,
    min_free_mb: int | None = None,
) -> dict[str, Any]:
    minimum_mb = (
        min_free_mb
        if min_free_mb is not None
        else _parse_int_env("REVBOT_MIN_FREE_DISK_MB", 200)
    )
    usage = shutil.disk_usage(Path(state_dir))
    free_mb = usage.free / (1024 * 1024)
    return {
        "ok": free_mb >= minimum_mb,
        "free_mb": round(free_mb, 2),
        "required_min_free_mb": int(minimum_mb),
    }


def check_timestamp_sanity(
    state_dir: str | Path,
    *,
    future_tolerance_seconds: float | None = None,
) -> dict[str, Any]:
    base = Path(state_dir)
    tolerance = (
        future_tolerance_seconds
        if future_tolerance_seconds is not None
        else _parse_float_env("REVBOT_MAX_FUTURE_FILE_SECONDS", 600.0)
    )
    now = time.time()

    future_files: list[dict[str, Any]] = []
    scanned = 0
    for file_name in ("config.json", "paper_state.json", "strategy_state.json", "trades.json"):
        path = base / file_name
        if not path.exists():
            continue
        scanned += 1
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > (now + tolerance):
            future_files.append(
                {
                    "file": file_name,
                    "mtime_epoch": mtime,
                    "delta_seconds": round(mtime - now, 2),
                }
            )

    return {
        "ok": not future_files,
        "scanned": scanned,
        "future_files": future_files,
        "future_tolerance_seconds": tolerance,
    }
