from __future__ import annotations

import json
import time
from pathlib import Path

from tools import decision_trace_audit


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    lines = [json.dumps(row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_run_audit_counts_and_reasons(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    rows = [
        {"ts_epoch": now - 60, "executed": False, "decision_reason": "insufficient_data"},
        {"ts_epoch": now - 55, "executed": False, "decision_reason": "insufficient_data"},
        {"ts_epoch": now - 50, "executed": False, "decision_reason": "atr_too_low"},
        {"ts_epoch": now - 45, "executed": True, "decision_reason": "bear_market_mean_reversion_buy"},
    ]
    _write_jsonl(state_dir / "decision_audit.jsonl", rows)
    monkeypatch.setattr(decision_trace_audit, "resolve_state_dir", lambda _default: state_dir)

    report = decision_trace_audit.run_audit(hours=1, limit=3)

    assert report["total_cycles"] == 4
    assert report["trades_executed"] == 1
    assert report["blocked_cycles"] == 3
    assert report["top_block_reasons"][0]["reason"] == "insufficient_data"
    assert report["top_block_reasons"][0]["count"] == 2


def test_run_audit_top_reason_detail_uses_gate_fields(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    rows = [
        {
            "ts_epoch": now - 120,
            "executed": False,
            "decision_reason": "market_data_quality:stale",
            "gate_trigger_condition": "candle_age_seconds > candle_stale_after_seconds",
            "gate_trigger_threshold": 420.0,
            "gate_trigger_actual": 510.0,
            "gate_trigger_correct": True,
        },
        {
            "ts_epoch": now - 110,
            "executed": False,
            "decision_reason": "market_data_quality:stale",
            "gate_trigger_condition": "candle_age_seconds > candle_stale_after_seconds",
            "gate_trigger_threshold": 420.0,
            "gate_trigger_actual": 690.0,
            "gate_trigger_correct": True,
        },
    ]
    _write_jsonl(state_dir / "decision_audit.jsonl", rows)
    monkeypatch.setattr(decision_trace_audit, "resolve_state_dir", lambda _default: state_dir)

    report = decision_trace_audit.run_audit(hours=1, limit=5)

    detail = report["top_reason_detail"]
    assert detail["reason"] == "market_data_quality:stale"
    assert detail["condition"] == "candle_age_seconds > candle_stale_after_seconds"
    assert detail["threshold_median"] == 420.0
    assert detail["actual_median"] == 600.0
    assert detail["decision_correct_rate_pct"] == 100.0


def test_run_audit_separates_advisory_only_vs_execution_block_reasons(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    rows = [
        {"ts_epoch": now - 60, "executed": False, "decision_reason": "insufficient_advisory"},
        {"ts_epoch": now - 55, "executed": False, "decision_reason": "volatility_insufficient"},
        {"ts_epoch": now - 50, "executed": False, "decision_reason": "market_data_quality:stale"},
    ]
    _write_jsonl(state_dir / "decision_audit.jsonl", rows)
    monkeypatch.setattr(decision_trace_audit, "resolve_state_dir", lambda _default: state_dir)

    report = decision_trace_audit.run_audit(hours=1, limit=5)
    assert report["blocked_cycles"] == 3
    assert report["advisory_only_blocked_cycles"] == 2
    assert report["execution_blocked_cycles"] == 1
    reasons = {row["reason"]: row for row in report["top_block_reasons"]}
    assert reasons["insufficient_advisory"]["advisory_only"] is True
    assert reasons["volatility_insufficient"]["execution_blocking"] is False
    assert reasons["market_data_quality:stale"]["execution_blocking"] is True


def test_run_audit_splits_entry_blocks_from_exit_hold_waiting_for_first_lock(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    rows = [
        {"ts_epoch": now - 60, "action": "HOLD", "executed": False, "decision_reason": "waiting_for_first_lock"},
        {"ts_epoch": now - 58, "action": "BUY", "executed": False, "decision_reason": "market_data_quality:stale"},
        {"ts_epoch": now - 55, "action": "BUY", "executed": False, "decision_reason": "insufficient_data"},
        {"ts_epoch": now - 52, "action": "BUY", "executed": True, "decision_reason": "bear_market_mean_reversion_buy"},
    ]
    _write_jsonl(state_dir / "decision_audit.jsonl", rows)
    monkeypatch.setattr(decision_trace_audit, "resolve_state_dir", lambda _default: state_dir)

    report = decision_trace_audit.run_audit(hours=1, limit=5)
    assert report["total_cycles"] == 4
    assert report["entry_blocked_cycles"] == 2
    assert report["exit_hold_cycles"] == 1
    assert report["execution_blocked_cycles"] == 2
    assert report["top_exit_hold_reasons"][0]["reason"] == "waiting_for_first_lock"
