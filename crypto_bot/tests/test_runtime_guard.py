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


def test_cleanup_log_rotations_removes_excess_files(tmp_path: Path):
    (tmp_path / "bot.log").write_text("base", encoding="utf-8")
    for idx in range(1, 8):
        (tmp_path / f"bot.log.{idx}").write_text(str(idx), encoding="utf-8")

    result = runtime_guard.cleanup_log_rotations(tmp_path, keep_rotations=5)
    assert result["removed_count"] == 2
    assert not (tmp_path / "bot.log.6").exists()
    assert not (tmp_path / "bot.log.7").exists()
    assert (tmp_path / "bot.log.5").exists()


def test_cleanup_large_jsonl_files_trims_to_tail_boundary(tmp_path: Path):
    rows = [f'{{"i":{idx}}}' for idx in range(200)]
    path = tmp_path / "decision_audit.jsonl"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    result = runtime_guard.cleanup_large_jsonl_files(
        tmp_path,
        file_names=("decision_audit.jsonl",),
        max_file_mb=0.001,  # force trimming
        keep_ratio=0.5,
    )
    assert result["trimmed_count"] == 1
    content = path.read_text(encoding="utf-8")
    assert content.startswith("{")
    assert content.endswith("\n")
    assert len(content.splitlines()) < len(rows)
