from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

DEFAULT_LOCK_TIMEOUT = 8.0
DEFAULT_LOCK_POLL_SECONDS = 0.05
DEFAULT_STALE_LOCK_SECONDS = 120.0
LOCK_WAIT_LOG_THRESHOLD_SECONDS = 1.0
DEFAULT_REPLACE_RETRIES = 8
DEFAULT_REPLACE_RETRY_DELAY_SECONDS = 0.05

logger = logging.getLogger("state_io")


def _parse_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_float_env(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(value, minimum)


def _parse_int_env(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(float(raw))
    except ValueError:
        return default
    return max(value, minimum)


STATE_IO_METRICS_ENABLED = _parse_bool_env("REVBOT_STATE_IO_METRICS", default=False)
STATE_IO_METRICS_INTERVAL_SECONDS = _parse_float_env(
    "REVBOT_STATE_IO_METRICS_INTERVAL_SECONDS",
    60.0,
    minimum=1.0,
)
STATE_IO_REPLACE_RETRIES = _parse_int_env(
    "REVBOT_STATE_IO_REPLACE_RETRIES",
    DEFAULT_REPLACE_RETRIES,
    minimum=0,
)
STATE_IO_REPLACE_RETRY_DELAY_SECONDS = _parse_float_env(
    "REVBOT_STATE_IO_REPLACE_RETRY_DELAY_SECONDS",
    DEFAULT_REPLACE_RETRY_DELAY_SECONDS,
    minimum=0.0,
)
_state_io_metrics: dict[str, dict[str, float | int]] = {}
_state_io_last_emit_at = time.monotonic()


def _emit_state_io_metrics(now: float):
    global _state_io_last_emit_at

    if not _state_io_metrics:
        _state_io_last_emit_at = now
        return

    top_items = sorted(
        _state_io_metrics.items(),
        key=lambda item: float(item[1].get("total_ms", 0.0)),
        reverse=True,
    )[:8]

    parts: list[str] = []
    for key, stats in top_items:
        count = max(int(stats.get("count", 0) or 0), 1)
        total_ms = float(stats.get("total_ms", 0.0) or 0.0)
        avg_ms = total_ms / count
        max_ms = float(stats.get("max_ms", 0.0) or 0.0)
        parts.append(
            f"{key} count={count} avg_ms={avg_ms:.3f} max_ms={max_ms:.3f}"
        )

    logger.info("state_io_metrics_window: " + " | ".join(parts))
    _state_io_metrics.clear()
    _state_io_last_emit_at = now


def _record_state_io_metric(operation: str, path: str | Path, elapsed_ms: float):
    if not STATE_IO_METRICS_ENABLED:
        return

    key = f"{operation}:{Path(path).name}"
    stats = _state_io_metrics.setdefault(
        key,
        {
            "count": 0,
            "total_ms": 0.0,
            "max_ms": 0.0,
        },
    )

    stats["count"] = int(stats["count"]) + 1
    stats["total_ms"] = float(stats["total_ms"]) + float(elapsed_ms)
    stats["max_ms"] = max(float(stats["max_ms"]), float(elapsed_ms))

    now = time.monotonic()
    if (now - _state_io_last_emit_at) >= STATE_IO_METRICS_INTERVAL_SECONDS:
        _emit_state_io_metrics(now)


@contextmanager
def file_lock(
    path: str | Path,
    *,
    timeout: float = DEFAULT_LOCK_TIMEOUT,
    poll_seconds: float = DEFAULT_LOCK_POLL_SECONDS,
    stale_seconds: float = DEFAULT_STALE_LOCK_SECONDS,
):
    target_path = Path(path)
    lock_path = target_path.with_name(f"{target_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    handle: int | None = None
    started_at = time.monotonic()
    wait_logged = False

    while True:
        try:
            handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(handle, str(os.getpid()).encode("ascii", errors="ignore"))
            break
        except FileExistsError:
            if stale_seconds > 0:
                try:
                    age_seconds = time.time() - lock_path.stat().st_mtime
                    if age_seconds > stale_seconds:
                        logger.warning(
                            f"Removing stale lock {lock_path} (age={age_seconds:.2f}s)"
                        )
                        try:
                            lock_path.unlink()
                        except FileNotFoundError:
                            pass
                        continue
                except FileNotFoundError:
                    continue

            waited = time.monotonic() - started_at
            if (not wait_logged) and waited >= LOCK_WAIT_LOG_THRESHOLD_SECONDS:
                holder = "unknown"
                try:
                    holder = lock_path.read_text(encoding="utf-8").strip() or "unknown"
                except Exception:
                    pass
                logger.warning(
                    f"Waiting for lock {lock_path} for {waited:.2f}s (holder={holder})"
                )
                wait_logged = True

            if waited >= timeout:
                message = f"Timed out waiting for lock: {lock_path}"
                logger.error(message)
                raise TimeoutError(message)

            time.sleep(poll_seconds)

    try:
        yield
    finally:
        if handle is not None:
            os.close(handle)

        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def state_transaction_lock(
    state_dir: str | Path,
    *,
    timeout: float = DEFAULT_LOCK_TIMEOUT,
):
    lock_target = Path(state_dir) / ".state_txn"
    with file_lock(lock_target, timeout=timeout):
        yield


def read_json_file(
    path: str | Path,
    *,
    default: Any = None,
    strict: bool = False,
):
    json_path = Path(path)
    started_at = time.perf_counter() if STATE_IO_METRICS_ENABLED else None

    try:
        # Accept UTF-8 BOM for compatibility with files edited by Windows tooling.
        with open(json_path, "r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except FileNotFoundError:
        if strict:
            raise
        return copy.deepcopy(default)
    except json.JSONDecodeError:
        if strict:
            raise
        return copy.deepcopy(default)
    finally:
        if started_at is not None:
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            _record_state_io_metric("read", json_path, elapsed_ms)


def write_json_atomic(
    path: str | Path,
    value: Any,
    *,
    indent: int = 2,
):
    json_path = Path(path)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    temp_file_path: str | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(json_path.parent),
            prefix=f".{json_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(value, handle, indent=indent)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temp_file_path = handle.name

        attempts = max(int(STATE_IO_REPLACE_RETRIES), 0)
        for attempt in range(attempts + 1):
            try:
                os.replace(temp_file_path, json_path)
                break
            except PermissionError:
                if attempt >= attempts:
                    raise
                sleep_seconds = STATE_IO_REPLACE_RETRY_DELAY_SECONDS * (attempt + 1)
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
            except OSError as exc:
                winerror = getattr(exc, "winerror", None)
                if (winerror not in {5, 32}) or attempt >= attempts:
                    raise
                sleep_seconds = STATE_IO_REPLACE_RETRY_DELAY_SECONDS * (attempt + 1)
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass


def write_json_file(
    path: str | Path,
    value: Any,
    *,
    indent: int = 2,
    timeout: float = DEFAULT_LOCK_TIMEOUT,
    use_lock: bool = True,
):
    json_path = Path(path)
    started_at = time.perf_counter() if STATE_IO_METRICS_ENABLED else None

    try:
        if use_lock:
            with file_lock(json_path, timeout=timeout):
                write_json_atomic(json_path, value, indent=indent)
            return

        write_json_atomic(json_path, value, indent=indent)
    finally:
        if started_at is not None:
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            metric_name = "write_locked" if use_lock else "write_unlocked"
            _record_state_io_metric(metric_name, json_path, elapsed_ms)


def mutate_json_file(
    path: str | Path,
    mutator: Callable[[Any], Any],
    *,
    default: Any = None,
    indent: int = 2,
    timeout: float = DEFAULT_LOCK_TIMEOUT,
):
    json_path = Path(path)
    started_at = time.perf_counter() if STATE_IO_METRICS_ENABLED else None

    try:
        with file_lock(json_path, timeout=timeout):
            current = read_json_file(json_path, default=default, strict=False)
            updated = mutator(current)
            if updated is None:
                updated = current
            write_json_atomic(json_path, updated, indent=indent)
            return updated
    finally:
        if started_at is not None:
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            _record_state_io_metric("mutate_locked", json_path, elapsed_ms)
