from __future__ import annotations

import json
from pathlib import Path

from utils import state_snapshot


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def test_create_state_snapshot_copies_known_files(tmp_path: Path):
    _write_json(tmp_path / "config.json", {"enabled": True})
    _write_json(tmp_path / "paper_state.json", {"balance": 100, "positions": {}})
    _write_json(tmp_path / "strategy_state.json", {})
    _write_json(tmp_path / "state.json", {})
    _write_json(tmp_path / "trades.json", [])

    snapshot_dir = state_snapshot.create_state_snapshot(
        reason="unit_test",
        state_dir=tmp_path,
    )

    assert snapshot_dir.exists()
    assert (snapshot_dir / "config.json").exists()
    assert (snapshot_dir / "paper_state.json").exists()
    assert (snapshot_dir / "manifest.json").exists()

    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["reason"] == "unit_test"
    assert "config.json" in manifest["copied_files"]


def test_ensure_daily_snapshot_only_runs_once_per_day(tmp_path: Path):
    _write_json(tmp_path / "config.json", {"enabled": True})
    _write_json(tmp_path / "paper_state.json", {"balance": 100, "positions": {}})
    _write_json(tmp_path / "strategy_state.json", {})
    _write_json(tmp_path / "state.json", {})
    _write_json(tmp_path / "trades.json", [])

    first = state_snapshot.ensure_daily_snapshot(
        reason="daily_test",
        state_dir=tmp_path,
    )
    second = state_snapshot.ensure_daily_snapshot(
        reason="daily_test",
        state_dir=tmp_path,
    )

    assert first is not None
    assert second is None
