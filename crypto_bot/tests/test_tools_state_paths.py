from __future__ import annotations

import importlib
from pathlib import Path


TOOL_MODULES = (
    "tools.profit_profile_rollout",
    "tools.profit_profile_verify",
    "tools.regime_confidence_recalibration_report",
    "tools.live_safety_tuning_report",
    "tools.weekly_threshold_suggestion_report",
    "tools.sync_health_report",
    "tools.repair_core_candles",
)


def test_tool_default_state_dirs_use_runtime_root(tmp_path: Path, monkeypatch):
    runtime_root = tmp_path / "runtime_data"
    monkeypatch.setenv("BOT_DATA_DIR", str(runtime_root))

    expected_state = runtime_root / "state"
    for module_name in TOOL_MODULES:
        module = importlib.import_module(module_name)
        default_dir = module._default_state_dir()
        assert default_dir == expected_state
