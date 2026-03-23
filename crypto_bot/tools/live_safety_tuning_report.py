from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _f(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def main() -> int:
    parser = argparse.ArgumentParser(description="RevBot live safety tuning report.")
    parser.add_argument("--state-dir", default=str(Path(__file__).resolve().parents[1] / "state"))
    parser.add_argument("--hours", type=float, default=12.0)
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    sync_path = state_dir / "market_sync_health_history.jsonl"
    audit_path = state_dir / "decision_audit.jsonl"

    sync_rows = _load_jsonl(sync_path)
    audit_rows = _load_jsonl(audit_path)
    now = time.time()
    cutoff = now - (max(args.hours, 0.5) * 3600.0)
    sync_rows = [r for r in sync_rows if _f(r.get("ts_epoch"), 0) >= cutoff]
    audit_rows = [r for r in audit_rows if _f(r.get("ts_epoch"), 0) >= cutoff]

    report: dict = {
        "window_hours": max(args.hours, 0.5),
        "sync_samples": len(sync_rows),
        "audit_samples": len(audit_rows),
    }

    # Sync metrics
    if sync_rows:
        first_ts = _f(sync_rows[0].get("ts_epoch"), now)
        last_ts = _f(sync_rows[-1].get("ts_epoch"), now)
        eff_hours = max((last_ts - first_ts) / 3600.0, 1e-6)
        rl_sum = sum(_f(r.get("adaptive_budget", {}).get("pressure", {}).get("rate_limited_count")) for r in sync_rows)
        degraded_sum = sum(_f(r.get("sync", {}).get("degraded")) for r in sync_rows)
        req_sum = sum(_f(r.get("sync", {}).get("requests")) for r in sync_rows)
        new_sum = sum(_f(r.get("sync", {}).get("new_inserted")) for r in sync_rows)
        fresh_1h = [_f(r.get("coverage", {}).get("fresh_counts_by_timeframe", {}).get("1h")) for r in sync_rows]
        fresh_4h = [_f(r.get("coverage", {}).get("fresh_counts_by_timeframe", {}).get("4h")) for r in sync_rows]
        fresh_1d = [_f(r.get("coverage", {}).get("fresh_counts_by_timeframe", {}).get("1d")) for r in sync_rows]
        report["sync"] = {
            "effective_hours": round(eff_hours, 3),
            "rate_limited_events_per_hour_proxy": round(rl_sum / eff_hours, 3),
            "degraded_jobs_per_hour": round(degraded_sum / eff_hours, 3),
            "avg_requests_per_sample": round(req_sum / max(len(sync_rows), 1), 3),
            "avg_new_inserted_per_sample": round(new_sum / max(len(sync_rows), 1), 3),
            "fresh_1h_median": _median(fresh_1h),
            "fresh_4h_median": _median(fresh_4h),
            "fresh_24h_median": _median(fresh_1d),
            "fresh_1h_latest": int(fresh_1h[-1]) if fresh_1h else 0,
            "fresh_4h_latest": int(fresh_4h[-1]) if fresh_4h else 0,
            "fresh_24h_latest": int(fresh_1d[-1]) if fresh_1d else 0,
        }
    else:
        report["sync"] = {"note": "no sync samples in window"}

    # Decision audit metrics
    route_rows = [r for r in audit_rows if str(r.get("action", "")).upper() == "BUY"]
    non_mr = [
        r for r in route_rows
        if str(r.get("effective_route") or "").upper() not in {"", "MEAN_REVERSION", "MEAN_REVERSION_FRIENDLY"}
    ]
    blocked = [r for r in non_mr if not bool(r.get("executed", False))]
    executed = [r for r in non_mr if bool(r.get("executed", False))]
    blocked_reasons: dict[str, int] = {}
    for row in blocked:
        reason = str(row.get("blocked_reason") or "unknown")
        blocked_reasons[reason] = blocked_reasons.get(reason, 0) + 1
    conf_blocked = [_f(r.get("confidence_score")) for r in blocked if r.get("confidence_score") is not None]
    conf_exec = [_f(r.get("confidence_score")) for r in executed if r.get("confidence_score") is not None]
    report["audit"] = {
        "buy_rows": len(route_rows),
        "non_mr_buy_rows": len(non_mr),
        "non_mr_executed": len(executed),
        "non_mr_blocked": len(blocked),
        "non_mr_block_rate_pct": round((len(blocked) / max(len(non_mr), 1)) * 100.0, 2) if non_mr else 0.0,
        "blocked_reason_counts": dict(sorted(blocked_reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
        "confidence_median_blocked": _median(conf_blocked),
        "confidence_median_executed": _median(conf_exec),
    }

    # Simple tuning recommendations
    recs: list[str] = []
    sync = report.get("sync", {})
    audit = report.get("audit", {})
    rl_per_h = _f(sync.get("rate_limited_events_per_hour_proxy"))
    degraded_per_h = _f(sync.get("degraded_jobs_per_hour"))
    non_mr_block_rate = _f(audit.get("non_mr_block_rate_pct"))
    blocked_reason_counts = audit.get("blocked_reason_counts", {})

    if rl_per_h > 8:
        recs.append("High throttle pressure: reduce max_sync_requests_per_tick or increase loop_sleep by 2-3s.")
    elif rl_per_h < 2:
        recs.append("Throttle pressure low: safe to trial +1 sync request cap during active windows.")

    if degraded_per_h > 2:
        recs.append("Degraded sync elevated: prioritize symbol health demotion or widen unsupported backoff.")

    if non_mr_block_rate > 95 and len(non_mr) >= 20:
        recs.append("Non-MR guard very strict: if desired, lower route_quality_min_confidence by 3-5 points.")
    elif non_mr_block_rate < 20 and len(non_mr) >= 20:
        recs.append("Non-MR routing permissive: consider tightening route_quality_min_stability/persistence by +5.")

    if isinstance(blocked_reason_counts, dict):
        if blocked_reason_counts.get("route_quality_throttle_pressure", 0) > 0:
            recs.append("Frequent throttle-pressure blocks: reduce sync request cap baseline by 1.")
        if blocked_reason_counts.get("route_quality_low_confidence", 0) > 0:
            recs.append("Low-confidence is major blocker: keep confidence gate; improve candle freshness before lowering.")

    if not recs:
        recs.append("No major pressure signals. Keep current thresholds and re-evaluate after another 12h window.")

    report["recommendations"] = recs
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

