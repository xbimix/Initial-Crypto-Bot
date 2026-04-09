from __future__ import annotations

import os
from pathlib import Path

from utils.state_integrity_report import build_state_integrity_report


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_state_integrity_report_no_collision(tmp_path: Path):
    active = tmp_path / "runtime" / "state"
    legacy = tmp_path / "legacy" / "state"
    _write(active / "config.json", "{}")
    _write(active / "paper_state.json", '{"balance":1000,"positions":{}}')

    report = build_state_integrity_report(
        default_state_dir=legacy,
        active_state_dir=active,
        required_filenames=("config.json", "paper_state.json"),
    )
    assert report.ok is True
    assert report.collision_count == 0
    assert report.used_legacy_count == 0


def test_state_integrity_report_detects_legacy_newer_collision(tmp_path: Path):
    active = tmp_path / "runtime" / "state"
    legacy = tmp_path / "legacy" / "state"
    primary = active / "config.json"
    legacy_file = legacy / "config.json"
    _write(primary, '{"mode":"runtime"}')
    _write(legacy_file, '{"mode":"legacy"}')
    os.utime(primary, (1_700_000_000, 1_700_000_000))
    os.utime(legacy_file, (1_800_000_000, 1_800_000_000))

    report = build_state_integrity_report(
        default_state_dir=legacy,
        active_state_dir=active,
        required_filenames=("config.json",),
    )
    assert report.ok is False
    assert report.collision_count == 1
    assert report.files[0].collision_reason == "legacy_newer_than_primary"


def test_state_integrity_report_marks_legacy_fallback_usage(tmp_path: Path):
    active = tmp_path / "runtime" / "state"
    legacy = tmp_path / "legacy" / "state"
    _write(legacy / "trades.json", "[]")

    report = build_state_integrity_report(
        default_state_dir=legacy,
        active_state_dir=active,
        required_filenames=("trades.json",),
    )
    assert report.ok is True
    assert report.collision_count == 0
    assert report.used_legacy_count == 1
    assert report.files[0].used_legacy_fallback is True
