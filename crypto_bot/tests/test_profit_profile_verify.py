from __future__ import annotations

import json
from pathlib import Path

from tools import profit_profile_verify as verify


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(row) for row in rows)
    if payload:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")


def test_build_verification_report_passes_when_slos_hold(tmp_path: Path):
    state_dir = tmp_path / "state"
    now = 10_000.0
    reference_ts = 9_000.0
    _write_json(
        state_dir / "config.json",
        {
            "market_data": {
                "freshness_slo": {
                    "min_fresh_1h": 1,
                    "min_fresh_4h": 1,
                    "max_degraded_jobs": 3,
                }
            }
        },
    )
    _write_jsonl(
        state_dir / "market_sync_health_history.jsonl",
        [
            {
                "ts_epoch": 9_200.0,
                "sync": {"degraded": 0},
                "coverage": {"fresh_counts_by_timeframe": {"1h": 2, "4h": 1}},
            },
            {
                "ts_epoch": 9_800.0,
                "sync": {"degraded": 0},
                "coverage": {"fresh_counts_by_timeframe": {"1h": 3, "4h": 2}},
            },
        ],
    )
    _write_jsonl(
        state_dir / "decision_audit.jsonl",
        [
            {"ts_epoch": 9_500.0, "action": "BUY", "executed": True},
            {"ts_epoch": 9_700.0, "action": "BUY", "executed": False},
        ],
    )
    _write_json(
        state_dir / "trades.json",
        [
            {"time": 9_600.0, "symbol": "BTC-USD", "side": "SELL", "pnl": 5.0},
        ],
    )

    report = verify.build_verification_report(
        state_dir=state_dir,
        windows_hours=[12.0, 24.0],
        reference_ts=reference_ts,
        now_epoch=now,
    )
    assert report["overall_pass"] is True
    assert len(report["windows"]) == 2
    assert report["windows"][0]["checks"]["fresh_1h"] is True
    assert report["windows"][0]["checks"]["fresh_4h"] is True
    assert report["windows"][0]["checks"]["degraded_jobs"] is True


def test_build_verification_report_flags_failed_slos(tmp_path: Path):
    state_dir = tmp_path / "state"
    now = 10_000.0
    reference_ts = 9_000.0
    _write_json(
        state_dir / "config.json",
        {
            "market_data": {
                "freshness_slo": {
                    "min_fresh_1h": 2,
                    "min_fresh_4h": 2,
                    "max_degraded_jobs": 1,
                }
            }
        },
    )
    _write_jsonl(
        state_dir / "market_sync_health_history.jsonl",
        [
            {
                "ts_epoch": 9_900.0,
                "sync": {"degraded": 4},
                "coverage": {"fresh_counts_by_timeframe": {"1h": 1, "4h": 0}},
            },
        ],
    )
    _write_jsonl(state_dir / "decision_audit.jsonl", [])
    _write_json(state_dir / "trades.json", [])

    report = verify.build_verification_report(
        state_dir=state_dir,
        windows_hours=[12.0],
        reference_ts=reference_ts,
        now_epoch=now,
    )
    assert report["overall_pass"] is False
    window = report["windows"][0]
    assert window["pass"] is False
    assert "fresh_1h" in window["failed_checks"]
    assert "fresh_4h" in window["failed_checks"]
    assert "degraded_jobs" in window["failed_checks"]
