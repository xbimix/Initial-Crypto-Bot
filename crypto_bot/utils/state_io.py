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

logger = logging.getLogger("state_io")


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

    try:
        with open(json_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        if strict:
            raise
        return copy.deepcopy(default)
    except json.JSONDecodeError:
        if strict:
            raise
        return copy.deepcopy(default)


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

        os.replace(temp_file_path, json_path)
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
    if use_lock:
        with file_lock(path, timeout=timeout):
            write_json_atomic(path, value, indent=indent)
        return

    write_json_atomic(path, value, indent=indent)


def mutate_json_file(
    path: str | Path,
    mutator: Callable[[Any], Any],
    *,
    default: Any = None,
    indent: int = 2,
    timeout: float = DEFAULT_LOCK_TIMEOUT,
):
    with file_lock(path, timeout=timeout):
        current = read_json_file(path, default=default, strict=False)
        updated = mutator(current)
        if updated is None:
            updated = current
        write_json_atomic(path, updated, indent=indent)
        return updated
