from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
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


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _pct(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return (numerator / denominator) * 100.0


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def _default_state_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    runtime_state = repo_root / ".runtime" / "state"
    if runtime_state.exists():
        return runtime_state
    return Path(__file__).resolve().parents[1] / "state"


def _latest_rollout_ts(docs_dir: Path) -> float | None:
    rows = _load_jsonl(docs_dir / "profit_profile_change_log.jsonl")
    if not rows:
        return None
    latest = max((_f(row.get("ts_epoch"), 0.0) for row in rows), default=0.0)
    return latest if latest > 0 else None


def _window_metrics(
    *,
    window_hours: float,
    now_epoch: float,
    reference_ts: float,
    sync_rows: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
    slo: dict[str, Any],
) -> dict[str, Any]:
    window_start = max(reference_ts, now_epoch - (window_hours * 3600.0))
    window_sync = [row for row in sync_rows if _f(row.get("ts_epoch"), 0.0) >= window_start]
    window_audit = [row for row in audit_rows if _f(row.get("ts_epoch"), 0.0) >= window_start]
    window_trades = [row for row in trade_rows if _f(row.get("time"), 0.0) >= window_start]

    if window_sync:
        first_ts = _f(window_sync[0].get("ts_epoch"), now_epoch)
        last_ts = _f(window_sync[-1].get("ts_epoch"), now_epoch)
        effective_hours = max((last_ts - first_ts) / 3600.0, 1e-6)
        degraded_jobs_per_hour = (
            sum(_f(row.get("sync", {}).get("degraded"), 0.0) for row in window_sync) / effective_hours
        )
        fresh_1h_values = [
            _f(row.get("coverage", {}).get("fresh_counts_by_timeframe", {}).get("1h"), 0.0)
            for row in window_sync
        ]
        fresh_4h_values = [
            _f(row.get("coverage", {}).get("fresh_counts_by_timeframe", {}).get("4h"), 0.0)
            for row in window_sync
        ]
        fresh_1h_latest = int(fresh_1h_values[-1]) if fresh_1h_values else 0
        fresh_4h_latest = int(fresh_4h_values[-1]) if fresh_4h_values else 0
        fresh_1h_median = _median([float(v) for v in fresh_1h_values])
        fresh_4h_median = _median([float(v) for v in fresh_4h_values])
    else:
        effective_hours = max((now_epoch - window_start) / 3600.0, 1e-6)
        degraded_jobs_per_hour = float("inf")
        fresh_1h_latest = 0
        fresh_4h_latest = 0
        fresh_1h_median = None
        fresh_4h_median = None

    buy_rows = [row for row in window_audit if str(row.get("action") or "").strip().upper() == "BUY"]
    buy_executed = [row for row in buy_rows if bool(row.get("executed", False))]
    buy_blocked = [row for row in buy_rows if not bool(row.get("executed", False))]
    sell_rows = [row for row in window_trades if str(row.get("side") or "").strip().upper() == "SELL"]
    realized_pnl_usd = sum(_f(row.get("pnl"), 0.0) for row in sell_rows)
    expectancy_per_sell = (
        realized_pnl_usd / max(float(len(sell_rows)), 1.0)
        if sell_rows
        else None
    )

    min_fresh_1h = int(_f(slo.get("min_fresh_1h"), 0.0))
    min_fresh_4h = int(_f(slo.get("min_fresh_4h"), 0.0))
    max_degraded_jobs = _f(slo.get("max_degraded_jobs"), 0.0)
    checks = {
        "has_sync_samples": len(window_sync) > 0,
        "fresh_1h": fresh_1h_latest >= min_fresh_1h,
        "fresh_4h": fresh_4h_latest >= min_fresh_4h,
        "degraded_jobs": degraded_jobs_per_hour <= max_degraded_jobs,
    }
    overall_pass = all(bool(value) for value in checks.values())
    failed_checks = [name for name, value in checks.items() if not bool(value)]

    return {
        "window_hours": window_hours,
        "window_start_ts": window_start,
        "window_end_ts": now_epoch,
        "sync_samples": len(window_sync),
        "audit_samples": len(window_audit),
        "trade_rows": len(window_trades),
        "metrics": {
            "effective_hours": round(effective_hours, 3),
            "degraded_jobs_per_hour": round(degraded_jobs_per_hour, 3)
            if degraded_jobs_per_hour != float("inf")
            else None,
            "fresh_1h_latest": fresh_1h_latest,
            "fresh_4h_latest": fresh_4h_latest,
            "fresh_1h_median": fresh_1h_median,
            "fresh_4h_median": fresh_4h_median,
            "buy_attempts": len(buy_rows),
            "buy_executed": len(buy_executed),
            "buy_blocked": len(buy_blocked),
            "buy_rejection_rate_pct": round(
                _pct(float(len(buy_blocked)), max(float(len(buy_rows)), 1.0)),
                3,
            )
            if buy_rows
            else 0.0,
            "sell_count": len(sell_rows),
            "realized_pnl_usd": round(realized_pnl_usd, 6),
            "expectancy_per_sell_usd": (
                round(expectancy_per_sell, 6)
                if expectancy_per_sell is not None
                else None
            ),
        },
        "slo_thresholds": {
            "min_fresh_1h": min_fresh_1h,
            "min_fresh_4h": min_fresh_4h,
            "max_degraded_jobs": max_degraded_jobs,
        },
        "checks": checks,
        "failed_checks": failed_checks,
        "pass": overall_pass,
    }


def build_verification_report(
    *,
    state_dir: Path,
    windows_hours: list[float],
    reference_ts: float,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    now = float(now_epoch if now_epoch is not None else time.time())
    config = _load_json(state_dir / "config.json", {})
    if not isinstance(config, dict):
        config = {}
    market_data = config.get("market_data", {})
    if not isinstance(market_data, dict):
        market_data = {}
    freshness_slo = market_data.get("freshness_slo", {})
    if not isinstance(freshness_slo, dict):
        freshness_slo = {}

    sync_rows = _load_jsonl(state_dir / "market_sync_health_history.jsonl")
    audit_rows = _load_jsonl(state_dir / "decision_audit.jsonl")
    trade_rows = _load_json(state_dir / "trades.json", [])
    if not isinstance(trade_rows, list):
        trade_rows = []

    windows = sorted({max(float(value), 0.5) for value in windows_hours})
    window_reports = [
        _window_metrics(
            window_hours=window,
            now_epoch=now,
            reference_ts=reference_ts,
            sync_rows=sync_rows,
            audit_rows=audit_rows,
            trade_rows=trade_rows,
            slo=freshness_slo,
        )
        for window in windows
    ]

    drift: dict[str, Any] = {}
    if len(window_reports) >= 2:
        shortest = window_reports[0]
        longest = window_reports[-1]
        drift = {
            "short_window_hours": shortest["window_hours"],
            "long_window_hours": longest["window_hours"],
            "degraded_jobs_per_hour_delta": round(
                _f(shortest["metrics"].get("degraded_jobs_per_hour"), 0.0)
                - _f(longest["metrics"].get("degraded_jobs_per_hour"), 0.0),
                6,
            ),
            "buy_rejection_rate_pct_delta": round(
                _f(shortest["metrics"].get("buy_rejection_rate_pct"), 0.0)
                - _f(longest["metrics"].get("buy_rejection_rate_pct"), 0.0),
                6,
            ),
            "expectancy_per_sell_usd_delta": round(
                _f(shortest["metrics"].get("expectancy_per_sell_usd"), 0.0)
                - _f(longest["metrics"].get("expectancy_per_sell_usd"), 0.0),
                6,
            ),
        }

    return {
        "generated_at_epoch": now,
        "state_dir": str(state_dir),
        "reference_ts": reference_ts,
        "windows": window_reports,
        "drift": drift,
        "overall_pass": all(bool(row.get("pass")) for row in window_reports),
        "note": (
            "Post-apply verification for profile rollout based on freshness SLO and execution/audit drift. "
            "Advisory-only; no config mutation."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify post-apply profile rollout SLO drift over 12h/24h windows.")
    parser.add_argument("--state-dir", default=str(_default_state_dir()))
    parser.add_argument("--reference-ts", type=float, default=None)
    parser.add_argument("--windows", default="12,24")
    parser.add_argument("--print-json", action="store_true")
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    if not state_dir.exists():
        raise FileNotFoundError(f"State directory not found: {state_dir}")

    repo_root = Path(__file__).resolve().parents[2]
    docs_dir = repo_root / "docs"
    reference_ts = _f(args.reference_ts, 0.0) if args.reference_ts is not None else 0.0
    if reference_ts <= 0:
        inferred = _latest_rollout_ts(docs_dir)
        if inferred is not None:
            reference_ts = inferred
        else:
            reference_ts = time.time() - (24.0 * 3600.0)

    windows_hours: list[float] = []
    for chunk in str(args.windows or "").split(","):
        raw = chunk.strip()
        if not raw:
            continue
        windows_hours.append(max(_f(raw, 0.0), 0.5))
    if not windows_hours:
        windows_hours = [12.0, 24.0]

    report = build_verification_report(
        state_dir=state_dir,
        windows_hours=windows_hours,
        reference_ts=reference_ts,
    )

    if args.print_json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"profile verification overall_pass={report['overall_pass']} "
            f"windows={','.join(str(int(row['window_hours'])) for row in report['windows'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
