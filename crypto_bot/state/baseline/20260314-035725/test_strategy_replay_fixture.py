from __future__ import annotations

from pathlib import Path

from utils.strategy_replay import run_replay_fixture


def test_strategy_replay_fixture_has_no_behavior_drift():
    fixture = Path(__file__).resolve().parent / "fixtures" / "strategy_replay_cases.json"
    report = run_replay_fixture(fixture)

    assert report["case_count"] > 0
    assert report["mismatch_count"] == 0, report["mismatches"][:10]
