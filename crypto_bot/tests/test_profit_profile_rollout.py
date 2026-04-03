from __future__ import annotations

import json
from pathlib import Path

from tools import profit_profile_rollout as rollout


def test_phase_payload_applies_expected_keys():
    cfg = {
        "risk": {"risk_percent": 0.02},
        "market_data": {"route_quality_guard_enabled": False},
    }
    updated, changed = rollout._phase_payload(cfg, "risk_sizing")

    assert isinstance(updated, dict)
    assert any(row["path"] == "risk.sizing_mode" for row in changed)
    assert updated["risk"]["sizing_mode"] == "auto"
    assert updated["risk"]["max_concurrent_trades_per_token"] == 1
    assert updated["risk"]["max_notional_usd"] == 750.0


def test_apply_phase_writes_config_and_backup(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    config_path = state_dir / "config.json"
    config_path.write_text(json.dumps({"risk": {}}, indent=2), encoding="utf-8")

    logs: list[dict] = []

    def _capture_log(**kwargs):
        logs.append(dict(kwargs))

    monkeypatch.setattr(rollout, "_append_rollout_log", _capture_log)

    result = rollout._apply_phase(
        state_dir=state_dir,
        phase="runtime_safety",
        dry_run=False,
    )

    assert result["phase"] == "runtime_safety"
    assert result["changed_count"] > 0
    assert "backup_path" in result
    assert Path(result["backup_path"]).exists()
    assert logs, "rollout log should be emitted"

    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    risk = persisted.get("risk", {})
    assert risk.get("daily_loss_limit_usd") == 150.0
    assert risk.get("max_consecutive_execution_failures") == 3
    assert risk.get("execution_failure_pause_seconds") == 300


def test_apply_phase_dry_run_does_not_mutate_file(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    config_path = state_dir / "config.json"
    original = {"market_data": {"route_quality_guard_enabled": False}}
    config_path.write_text(json.dumps(original, indent=2), encoding="utf-8")

    result = rollout._apply_phase(
        state_dir=state_dir,
        phase="data_integrity",
        dry_run=True,
    )

    assert result["dry_run"] is True
    current = json.loads(config_path.read_text(encoding="utf-8"))
    assert current == original


def test_profile_dry_run_preview_does_not_mutate_file(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    config_path = state_dir / "config.json"
    original = {"strategy_defaults": {"tuning_profile": "conservative"}, "risk": {"risk_percent": 0.01}}
    config_path.write_text(json.dumps(original, indent=2), encoding="utf-8")

    result = rollout._apply_profile(
        state_dir=state_dir,
        profile="balanced",
        dry_run=True,
        allow_risk_upshift=False,
        allow_profile_jump=False,
    )

    assert result["mode"] == "profile"
    assert result["profile"] == "balanced"
    assert result["dry_run"] is True
    assert result["transition_guard"]["allowed"] is False
    assert result["transition_guard"]["reason"] == "risk_upshift_requires_allow_flag"
    current = json.loads(config_path.read_text(encoding="utf-8"))
    assert current == original


def test_profile_apply_blocks_risk_upshift_without_allow_flag(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    config_path = state_dir / "config.json"
    config_path.write_text(
        json.dumps({"strategy_defaults": {"tuning_profile": "conservative"}, "risk": {}}, indent=2),
        encoding="utf-8",
    )

    try:
        rollout._apply_profile(
            state_dir=state_dir,
            profile="balanced",
            dry_run=False,
            allow_risk_upshift=False,
            allow_profile_jump=False,
        )
    except ValueError as exc:
        assert "risk_upshift_requires_allow_flag" in str(exc)
    else:
        raise AssertionError("Expected upshift guard to block apply")


def test_profile_apply_with_allow_flag_updates_config(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    config_path = state_dir / "config.json"
    config_path.write_text(
        json.dumps({"strategy_defaults": {"tuning_profile": "conservative"}, "risk": {}}, indent=2),
        encoding="utf-8",
    )

    logs: list[dict] = []

    def _capture_log(**kwargs):
        logs.append(dict(kwargs))

    monkeypatch.setattr(rollout, "_append_rollout_log", _capture_log)
    result = rollout._apply_profile(
        state_dir=state_dir,
        profile="balanced",
        dry_run=False,
        allow_risk_upshift=True,
        allow_profile_jump=False,
    )

    assert result["profile"] == "balanced"
    assert result["changed_count"] > 0
    assert "backup_path" in result
    assert Path(result["backup_path"]).exists()
    assert logs
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["strategy_defaults"]["tuning_profile"] == "balanced"
    assert persisted["risk"]["risk_percent"] == 0.015
