from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from reporting import slo_dashboard


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_build_slo_dashboard_outputs_metrics_and_trend_checks(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    reports_dir = state_dir / "reports"
    sync_history = state_dir / "market_sync_health_history.jsonl"
    decision_audit = state_dir / "decision_audit.jsonl"
    trades_path = state_dir / "trades.json"

    day_start = datetime(2026, 4, 2, tzinfo=timezone.utc).timestamp()
    prev_day_start = datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp()

    _write_jsonl(
        sync_history,
        [
            {"day_utc": "2026-04-01", "ts_epoch": prev_day_start + 1000.0, "coverage": {"status": "ok", "fresh_1h": 1, "fresh_4h": 1}},
            {"day_utc": "2026-04-01", "ts_epoch": prev_day_start + 2000.0, "coverage": {"status": "degraded", "fresh_1h": 0, "fresh_4h": 1}},
            {"day_utc": "2026-04-02", "ts_epoch": day_start + 1000.0, "coverage": {"status": "ok", "fresh_1h": 1, "fresh_4h": 1}},
            {"day_utc": "2026-04-02", "ts_epoch": day_start + 2000.0, "coverage": {"status": "ok", "fresh_1h": 1, "fresh_4h": 1}},
        ],
    )
    _write_jsonl(
        decision_audit,
            [
            {"day_utc": "2026-04-02", "ts_epoch": day_start + 1500.0, "executed": False, "blocked_reason": "route_share_cap"},
            {"day_utc": "2026-04-02", "ts_epoch": day_start + 1600.0, "executed": False, "blocked_reason": "route_share_cap"},
            {"day_utc": "2026-04-02", "ts_epoch": day_start + 1700.0, "executed": True},
            ],
        )
    _write_json(
        trades_path,
            [
            {"time": day_start + 1100.0, "symbol": "BTC-USD", "side": "BUY", "price": 100.0, "size": 1.0},
            {"time": day_start + 1900.0, "symbol": "BTC-USD", "side": "SELL", "price": 101.0, "size": 1.0, "effective_route": "trend_pullback", "realized_pnl_net_usd": 1.0},
            ],
        )

    monkeypatch.setattr(slo_dashboard, "STATE_DIR", state_dir)
    monkeypatch.setattr(slo_dashboard, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(slo_dashboard, "MARKET_SYNC_HEALTH_HISTORY_PATH", sync_history)
    monkeypatch.setattr(slo_dashboard, "DECISION_AUDIT_PATH", decision_audit)
    monkeypatch.setattr(slo_dashboard, "TRADES_PATH", trades_path)

    report = slo_dashboard.build_slo_dashboard("2026-04-02")
    assert report["schema_name"] == "slo_dashboard"
    assert report["schema_version"] == 1
    assert report["freshness"]["healthy_ratio"] == 1.0
    assert report["gate_blocks"]["total_blocked"] == 2
    assert report["gate_blocks"]["blocked_reason_counts"]["route_share_cap"] == 2
    assert report["execution"]["executions_count"] == 2
    assert report["execution"]["closed_trades_count"] == 1
    assert report["execution"]["expectancy_per_closed_trade_usd"] == 1.0
    assert report["execution"]["route_expectancy"]["trend_pullback"]["expectancy_per_trade_usd"] == 1.0
    assert len(report["trend_checks"]) == 3

    out = slo_dashboard.write_slo_dashboard(report)
    assert out.exists()
    latest = reports_dir / "slo_dashboard_latest.json"
    assert latest.exists()
