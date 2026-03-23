from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path


def _load_rows(path: Path) -> list[dict]:
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


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate RevBot sync health validation report.")
    parser.add_argument("--state-dir", default=str(Path(__file__).resolve().parents[1] / "state"))
    parser.add_argument("--hours", type=float, default=24.0)
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    history = state_dir / "market_sync_health_history.jsonl"
    rows = _load_rows(history)
    if not rows:
        print(json.dumps({"ok": False, "reason": "no_history_rows", "path": str(history)}, indent=2))
        return 1

    now = time.time()
    cutoff = now - (max(args.hours, 0.5) * 3600.0)
    scoped = [row for row in rows if _num(row.get("ts_epoch"), 0.0) >= cutoff]
    if not scoped:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": "no_rows_in_window",
                    "path": str(history),
                    "window_hours": max(args.hours, 0.5),
                },
                indent=2,
            )
        )
        return 1

    window_hours = max((_num(scoped[-1].get("ts_epoch"), now) - _num(scoped[0].get("ts_epoch"), now)) / 3600.0, 1e-6)
    rate_limited_sum = sum(
        _num(row.get("adaptive_budget", {}).get("pressure", {}).get("rate_limited_count"), 0.0)
        for row in scoped
    )
    degraded_sum = sum(_num(row.get("sync", {}).get("degraded"), 0.0) for row in scoped)
    errors_sum = sum(_num(row.get("sync", {}).get("errors"), 0.0) for row in scoped)
    requests_sum = sum(_num(row.get("sync", {}).get("requests"), 0.0) for row in scoped)
    new_inserted_sum = sum(_num(row.get("sync", {}).get("new_inserted"), 0.0) for row in scoped)

    fresh_1h = [_num(row.get("coverage", {}).get("fresh_counts_by_timeframe", {}).get("1h"), 0.0) for row in scoped]
    fresh_4h = [_num(row.get("coverage", {}).get("fresh_counts_by_timeframe", {}).get("4h"), 0.0) for row in scoped]
    fresh_1d = [_num(row.get("coverage", {}).get("fresh_counts_by_timeframe", {}).get("1d"), 0.0) for row in scoped]
    endpoint_official_success_sum = sum(
        _num(row.get("endpoint_telemetry", {}).get("official_success_calls"), 0.0)
        for row in scoped
    )
    endpoint_public_success_sum = sum(
        _num(row.get("endpoint_telemetry", {}).get("public_success_calls"), 0.0)
        for row in scoped
    )
    slo_status_counts: dict[str, int] = {}
    for row in scoped:
        status = str(row.get("slo", {}).get("status", "UNKNOWN")).upper()
        slo_status_counts[status] = int(slo_status_counts.get(status, 0) or 0) + 1

    report = {
        "ok": True,
        "path": str(history),
        "window_hours": round(window_hours, 3),
        "samples": len(scoped),
        "throttle_warnings_per_hour_proxy": round(rate_limited_sum / window_hours, 3),
        "degraded_jobs_per_hour": round(degraded_sum / window_hours, 3),
        "sync_errors_per_hour": round(errors_sum / window_hours, 3),
        "avg_requests_per_sample": round(requests_sum / max(len(scoped), 1), 3),
        "avg_new_inserted_per_sample": round(new_inserted_sum / max(len(scoped), 1), 3),
        "fresh_counts": {
            "1h_latest": int(fresh_1h[-1]),
            "4h_latest": int(fresh_4h[-1]),
            "24h_latest": int(fresh_1d[-1]),
            "1h_median": round(statistics.median(fresh_1h), 2),
            "4h_median": round(statistics.median(fresh_4h), 2),
            "24h_median": round(statistics.median(fresh_1d), 2),
        },
        "slo": {
            "latest_status": str(scoped[-1].get("slo", {}).get("status", "UNKNOWN")).upper(),
            "status_counts": slo_status_counts,
        },
        "endpoint_telemetry": {
            "official_success_calls_sum": int(endpoint_official_success_sum),
            "public_success_calls_sum": int(endpoint_public_success_sum),
            "latest_active_capability_count": len(
                (scoped[-1].get("endpoint_telemetry", {}).get("active_capabilities", {}) or {})
            ),
        },
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
