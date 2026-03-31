from __future__ import annotations

from pathlib import Path

from utils.state_paths import (
    read_path_with_legacy_fallback,
    resolve_state_dir,
    seed_primary_from_legacy,
)


def test_resolve_state_dir_uses_runtime_data_dir_by_default(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BOT_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("REVBOT_STATE_DIR", raising=False)
    path = resolve_state_dir(tmp_path / "legacy_default_state")
    assert path == (tmp_path / "runtime" / "legacy_default_state")
    assert path.exists()


def test_resolve_state_dir_honors_legacy_env_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BOT_DATA_DIR", str(tmp_path / "runtime"))
    override = tmp_path / "override_state"
    monkeypatch.setenv("REVBOT_STATE_DIR", str(override))
    path = resolve_state_dir(tmp_path / "ignored_default")
    assert path == override
    assert path.exists()


def test_read_path_with_legacy_fallback_prefers_legacy_when_primary_missing(tmp_path: Path):
    primary = tmp_path / "runtime" / "state" / "paper_state.json"
    legacy = tmp_path / "legacy" / "state" / "paper_state.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("{}", encoding="utf-8")
    assert read_path_with_legacy_fallback(primary, legacy) == legacy


def test_seed_primary_from_legacy_copies_once(tmp_path: Path):
    primary = tmp_path / "runtime" / "state" / "trades.json"
    legacy = tmp_path / "legacy" / "state" / "trades.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("[]", encoding="utf-8")

    copied = seed_primary_from_legacy(primary, legacy)
    assert copied is True
    assert primary.exists()
    assert primary.read_text(encoding="utf-8") == "[]"
