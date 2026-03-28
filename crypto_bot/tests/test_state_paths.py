from __future__ import annotations

from pathlib import Path

from utils.state_paths import resolve_state_dir


def test_resolve_state_dir_uses_default_when_env_missing(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("REVBOT_STATE_DIR", raising=False)
    path = resolve_state_dir(tmp_path / "default_state")
    assert path == (tmp_path / "default_state")
    assert path.exists()


def test_resolve_state_dir_honors_env_override(monkeypatch, tmp_path: Path):
    override = tmp_path / "override_state"
    monkeypatch.setenv("REVBOT_STATE_DIR", str(override))
    path = resolve_state_dir(tmp_path / "ignored_default")
    assert path == override
    assert path.exists()
