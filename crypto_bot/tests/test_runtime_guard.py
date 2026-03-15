from __future__ import annotations

import os
import time
from pathlib import Path

from utils import runtime_guard


def test_cleanup_stale_locks_removes_old_files(tmp_path: Path):
    stale_lock = tmp_path / "sample.json.lock"
    stale_lock.write_text("123", encoding="utf-8")
    old_time = time.time() - 3600
    os.utime(stale_lock, (old_time, old_time))

    fresh_lock = tmp_path / "fresh.json.lock"
    fresh_lock.write_text("123", encoding="utf-8")

    result = runtime_guard.cleanup_stale_locks(tmp_path, stale_seconds=60)
    assert result["removed_count"] == 1
    assert not stale_lock.exists()
    assert fresh_lock.exists()


def test_check_timestamp_sanity_detects_future_file(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    future = time.time() + 3600
    os.utime(config_path, (future, future))

    result = runtime_guard.check_timestamp_sanity(
        tmp_path,
        future_tolerance_seconds=30,
    )
    assert result["ok"] is False
    assert result["future_files"]


def test_check_disk_space_has_expected_keys(tmp_path: Path):
    result = runtime_guard.check_disk_space(tmp_path, min_free_mb=1)
    assert "ok" in result
    assert "free_mb" in result
    assert result["required_min_free_mb"] == 1
