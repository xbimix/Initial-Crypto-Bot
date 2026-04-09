from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from utils.state_paths import resolve_state_dir

STATE_DIR = resolve_state_dir(Path(__file__).resolve().parent.parent / "state")
REPORTS_DIR = STATE_DIR / "reports"
MARKET_SYNC_HEALTH_HISTORY_PATH = STATE_DIR / "market_sync_health_history.jsonl"
DECISION_AUDIT_PATH = STATE_DIR / "decision_audit.jsonl"
TRADES_PATH = STATE_DIR / "trades.json"

SLO_DASHBOARD_SCHEMA_NAME = "slo_dashboard"
SLO_DASHBOARD_SCHEMA_VERSION = 1


def _to_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _read_json(path: Path, default: Any):
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return default
    if not raw.strip():
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _iter_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _day_bounds(day_utc: str) -> tuple[float, float]:
    day_start = datetime.strptime(day_utc, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    return day_start.timestamp(), day_end.timestamp()


def _rows_for_day(rows: list[dict[str, Any]], day_utc: str, *, ts_key: str) -> list[dict[str, Any]]:
    start_ts, end_ts = _day_bounds(day_utc)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        row_day = row.get("day_utc")
        if row_day == day_utc:
            filtered.append(row)
            continue
        ts = _to_float(row.get(ts_key), fallback=0.0)
        if start_ts <= ts < end_ts:
            filtered.append(row)
    return filtered


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _freshness_summary(sync_rows: list[dict[str, Any]]) -> dict[str, Any]:
    sample_count = len(sync_rows)
    degraded = 0
    for row in sync_rows:
        coverage = row.get("coverage")
        if not isinstance(coverage, dict):
            degraded += 1
            continue
        status = str(coverage.get("status") or "").lower()
        if status and status != "ok":
            degraded += 1
            continue
        fresh_1h = _to_float(coverage.get("fresh_1h"), fallback=-1.0)
        fresh_4h = _to_float(coverage.get("fresh_4h"), fallback=-1.0)
        if fresh_1h < 1 or fresh_4h < 1:
            degraded += 1
    healthy = max(sample_count - degraded, 0)
    return {
        "sample_count": sample_count,
        "healthy_sample_count": healthy,
        "degraded_sample_count": degraded,
        "healthy_ratio": round(_safe_div(healthy, sample_count), 4),
    }


def _blocked_reason_summary(audit_rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    total_blocked = 0
    for row in audit_rows:
        if bool(row.get("executed")):
            continue
        reason = str(row.get("blocked_reason") or row.get("decision_reason") or "unknown")
        counts[reason] = int(counts.get(reason, 0) + 1)
        total_blocked += 1
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]
    return {
        "total_blocked": total_blocked,
        "blocked_reason_counts": {k: v for k, v in top},
    }


def _execution_summary(trades: list[dict[str, Any]], *, day_utc: str) -> dict[str, Any]:
    start_ts, end_ts = _day_bounds(day_utc)
    day_rows = [
        row for row in trades
        if start_ts <= _to_float(row.get("time"), 0.0) < end_ts
    ]
    executed_count = len(day_rows)
    hours = 24.0
    executions_per_hour = round(_safe_div(executed_count, hours), 4)
    sell_rows = [row for row in day_rows if str(row.get("side") or "").upper() == "SELL"]
    expectancy_values = [_to_float(row.get("realized_pnl_net_usd"), _to_float(row.get("pnl"), 0.0)) for row in sell_rows]
    expectancy = round(_safe_div(sum(expectancy_values), len(expectancy_values)), 6) if expectancy_values else 0.0

    route_stats: dict[str, dict[str, Any]] = {}
    for row in sell_rows:
        route = str(row.get("effective_route") or row.get("entry_route") or "unknown").strip().lower() or "unknown"
        bucket = route_stats.setdefault(route, {"closed_trades": 0, "net_pnl_usd": 0.0})
        bucket["closed_trades"] += 1
        bucket["net_pnl_usd"] += _to_float(row.get("realized_pnl_net_usd"), _to_float(row.get("pnl"), 0.0))
    for route, bucket in route_stats.items():
        closed = int(bucket["closed_trades"])
        net = float(bucket["net_pnl_usd"])
        bucket["expectancy_per_trade_usd"] = round(_safe_div(net, closed), 6)
        bucket["net_pnl_usd"] = round(net, 6)

    return {
        "executions_count": executed_count,
        "executions_per_hour": executions_per_hour,
        "closed_trades_count": len(sell_rows),
        "expectancy_per_closed_trade_usd": expectancy,
        "route_expectancy": dict(sorted(route_stats.items(), key=lambda item: item[0])),
    }


def _trend_checks(current: dict[str, Any], previous: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    current_fresh = _to_float(current.get("freshness", {}).get("healthy_ratio"), 0.0)
    prev_fresh = _to_float(previous.get("freshness", {}).get("healthy_ratio"), 0.0)
    checks.append(
        {
            "name": "freshness_non_degrading",
            "passed": current_fresh >= (prev_fresh - 0.05),
            "current": round(current_fresh, 4),
            "previous": round(prev_fresh, 4),
        }
    )

    current_exec = _to_float(current.get("execution", {}).get("executions_count"), 0.0)
    prev_exec = _to_float(previous.get("execution", {}).get("executions_count"), 0.0)
    checks.append(
        {
            "name": "execution_activity_not_collapsing",
            "passed": current_exec >= (prev_exec * 0.5),
            "current": current_exec,
            "previous": prev_exec,
        }
    )

    current_expectancy = _to_float(current.get("execution", {}).get("expectancy_per_closed_trade_usd"), 0.0)
    prev_expectancy = _to_float(previous.get("execution", {}).get("expectancy_per_closed_trade_usd"), 0.0)
    checks.append(
        {
            "name": "expectancy_not_sharply_worse",
            "passed": current_expectancy >= (prev_expectancy - abs(prev_expectancy) * 0.5 - 1e-9),
            "current": round(current_expectancy, 6),
            "previous": round(prev_expectancy, 6),
        }
    )
    return checks


def build_slo_dashboard(day_utc: str) -> dict[str, Any]:
    previous_day = (
        datetime.strptime(day_utc, "%Y-%m-%d").replace(tzinfo=timezone.utc) - timedelta(days=1)
    ).date().isoformat()
    sync_rows = _iter_jsonl_rows(MARKET_SYNC_HEALTH_HISTORY_PATH)
    audit_rows = _iter_jsonl_rows(DECISION_AUDIT_PATH)
    trades = _read_json(TRADES_PATH, default=[])
    if not isinstance(trades, list):
        trades = []

    current_sync = _rows_for_day(sync_rows, day_utc, ts_key="ts_epoch")
    previous_sync = _rows_for_day(sync_rows, previous_day, ts_key="ts_epoch")
    current_audit = _rows_for_day(audit_rows, day_utc, ts_key="ts_epoch")
    previous_audit = _rows_for_day(audit_rows, previous_day, ts_key="ts_epoch")

    current = {
        "freshness": _freshness_summary(current_sync),
        "gate_blocks": _blocked_reason_summary(current_audit),
        "execution": _execution_summary(trades, day_utc=day_utc),
    }
    previous = {
        "freshness": _freshness_summary(previous_sync),
        "gate_blocks": _blocked_reason_summary(previous_audit),
        "execution": _execution_summary(trades, day_utc=previous_day),
    }

    return {
        "schema_name": SLO_DASHBOARD_SCHEMA_NAME,
        "schema_version": SLO_DASHBOARD_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "day_utc": day_utc,
        "previous_day_utc": previous_day,
        "freshness": current["freshness"],
        "gate_blocks": current["gate_blocks"],
        "execution": current["execution"],
        "trend_checks": _trend_checks(current, previous),
        "state_references": {
            "market_sync_health_history_path": str(MARKET_SYNC_HEALTH_HISTORY_PATH),
            "decision_audit_path": str(DECISION_AUDIT_PATH),
            "trades_path": str(TRADES_PATH),
        },
    }


def write_slo_dashboard(report: dict[str, Any], *, output_path: Path | None = None) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    day_utc = str(report.get("day_utc") or "").strip()
    if not day_utc:
        raise ValueError("Report missing day_utc")
    target = output_path or (REPORTS_DIR / f"slo_dashboard_{day_utc}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest = REPORTS_DIR / "slo_dashboard_latest.json"
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return target

