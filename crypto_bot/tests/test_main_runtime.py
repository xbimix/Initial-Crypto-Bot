from __future__ import annotations

from pathlib import Path

import main as bot_main
from utils.state_io import write_json_file


def _seed_state_files(state_dir: Path):
    write_json_file(state_dir / "config.json", {"enabled": False, "symbols": []})
    write_json_file(state_dir / "paper_state.json", {"balance": 10000, "positions": {}})
    write_json_file(state_dir / "strategy_state.json", {})
    write_json_file(state_dir / "trades.json", [])


def test_startup_checks_ok(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    _seed_state_files(state_dir)

    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)
    monkeypatch.setattr(bot_main, "load_config", lambda: {"enabled": False})

    status = bot_main._run_startup_checks()
    assert status["ok"] is True
    names = {check["name"] for check in status["checks"]}
    assert "state_dir_exists" in names
    assert "state_dir_writable" in names
    assert "config_loadable" in names


def test_startup_checks_fail_when_config_unloadable(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    _seed_state_files(state_dir)

    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)

    def _fail():
        raise RuntimeError("config boom")

    monkeypatch.setattr(bot_main, "load_config", _fail)

    status = bot_main._run_startup_checks()
    assert status["ok"] is False
    failed = [item for item in status["checks"] if item["name"] == "config_loadable"]
    assert failed
    assert failed[0]["ok"] is False
