from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
REPORTS_DIR = STATE_DIR / "reports"


@dataclass(frozen=True)
class WeeklyWindow:
    start_day_utc: str
    end_day_utc: str
    day_count: int


def _parse_day(day_iso: str) -> date:
    return date.fromisoformat(day_iso)


def _read_json(path: Path) -> Any:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return None
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _day_window(end_day_iso: str, day_count: int) -> WeeklyWindow:
    end_day = _parse_day(end_day_iso)
    count = max(1, int(day_count))
    start_day = end_day - timedelta(days=count - 1)
    return WeeklyWindow(
        start_day_utc=start_day.isoformat(),
        end_day_utc=end_day.isoformat(),
        day_count=count,
    )


def _report_path_for_day(day_iso: str) -> Path:
    return REPORTS_DIR / f"daily_summary_{day_iso}.json"


def _to_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _to_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _iter_days(start_day_iso: str, end_day_iso: str):
    current = _parse_day(start_day_iso)
    end = _parse_day(end_day_iso)
    while current <= end:
        yield current.isoformat()
        current += timedelta(days=1)


def _aggregate_reason_counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        trade_reasons = row.get("trade_reasons", {})
        if not isinstance(trade_reasons, dict):
            continue
        reason_map = trade_reasons.get(key, {})
        if not isinstance(reason_map, dict):
            continue
        for reason, raw_count in reason_map.items():
            count = _to_int(raw_count, 0)
            if count <= 0:
                continue
            counts[reason] = counts.get(reason, 0) + count
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _build_anomaly_notes(rows: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []

    for row in rows:
        day = str(row.get("day_utc") or "unknown")
        run_quality = row.get("run_quality", {})
        summary = row.get("summary", {})
        if not isinstance(run_quality, dict):
            run_quality = {}
        if not isinstance(summary, dict):
            summary = {}

        crashes = _to_int(run_quality.get("crash_count"), 0)
        restarts = _to_int(run_quality.get("restart_count"), 0)
        data_gaps = _to_int(run_quality.get("data_gap_incidents"), 0)
        stale_blocks = _to_int(run_quality.get("stale_data_blocks"), 0)
        net_pnl = _to_float(summary.get("net_paper_pnl_usd"), 0.0)

        if crashes > 0:
            notes.append(f"{day}: crash_count={crashes}")
        if restarts >= 5:
            notes.append(f"{day}: restart_count={restarts} (high)")
        if data_gaps > 0:
            notes.append(f"{day}: data_gap_incidents={data_gaps}")
        if stale_blocks >= 500:
            notes.append(f"{day}: stale_data_blocks={stale_blocks} (high)")
        if net_pnl <= -200:
            notes.append(f"{day}: net_paper_pnl_usd={net_pnl:.2f} (deep negative)")

    return notes


def build_weekly_summary(
    end_day_iso: str | None = None,
    *,
    day_count: int = 7,
) -> dict[str, Any]:
    if not end_day_iso:
        end_day_iso = datetime.now(timezone.utc).date().isoformat()
    window = _day_window(end_day_iso, day_count)

    rows: list[dict[str, Any]] = []
    missing_days: list[str] = []
    for day_iso in _iter_days(window.start_day_utc, window.end_day_utc):
        path = _report_path_for_day(day_iso)
        row = _read_json(path)
        if isinstance(row, dict):
            rows.append(row)
        else:
            missing_days.append(day_iso)

    rows.sort(key=lambda item: str(item.get("day_utc") or ""))

    realized_total = sum(
        _to_float(row.get("summary", {}).get("realized_pnl_usd"), 0.0)
        for row in rows
        if isinstance(row.get("summary"), dict)
    )
    latest_unrealized = (
        _to_float(rows[-1].get("summary", {}).get("unrealized_pnl_usd"), 0.0)
        if rows and isinstance(rows[-1].get("summary"), dict)
        else 0.0
    )
    latest_net = (
        _to_float(rows[-1].get("summary", {}).get("net_paper_pnl_usd"), 0.0)
        if rows and isinstance(rows[-1].get("summary"), dict)
        else 0.0
    )
    latest_stale_losing_review_count = (
        _to_int(rows[-1].get("summary", {}).get("stale_losing_review_count"), 0)
        if rows and isinstance(rows[-1].get("summary"), dict)
        else 0
    )
    latest_max_drawdown_during_trade_pct = (
        _to_float(
            rows[-1].get("summary", {}).get(
                "max_drawdown_during_trade_pct",
                rows[-1].get("summary", {}).get("max_open_drawdown_pct", 0.0),
            ),
            0.0,
        )
        if rows and isinstance(rows[-1].get("summary"), dict)
        else 0.0
    )
    latest_max_drawdown_during_trade_symbol = (
        str(rows[-1].get("summary", {}).get("max_drawdown_during_trade_symbol") or "")
        if rows and isinstance(rows[-1].get("summary"), dict)
        else ""
    )
    drawdown_worst = min(
        (
            _to_float(row.get("summary", {}).get("max_open_drawdown_pct"), 0.0)
            for row in rows
            if isinstance(row.get("summary"), dict)
        ),
        default=0.0,
    )
    drawdown_during_trade_worst = min(
        (
            _to_float(
                row.get("summary", {}).get(
                    "max_drawdown_during_trade_pct",
                    row.get("summary", {}).get("max_open_drawdown_pct", 0.0),
                ),
                0.0,
            )
            for row in rows
            if isinstance(row.get("summary"), dict)
        ),
        default=0.0,
    )
    crash_total = sum(
        _to_int(row.get("run_quality", {}).get("crash_count"), 0)
        for row in rows
        if isinstance(row.get("run_quality"), dict)
    )
    restart_total = sum(
        _to_int(row.get("run_quality", {}).get("restart_count"), 0)
        for row in rows
        if isinstance(row.get("run_quality"), dict)
    )
    data_gap_total = sum(
        _to_int(row.get("run_quality", {}).get("data_gap_incidents"), 0)
        for row in rows
        if isinstance(row.get("run_quality"), dict)
    )
    stale_block_total = sum(
        _to_int(row.get("run_quality", {}).get("stale_data_blocks"), 0)
        for row in rows
        if isinstance(row.get("run_quality"), dict)
    )
    stale_losing_review_total = sum(
        _to_int(row.get("summary", {}).get("stale_losing_review_count"), 0)
        for row in rows
        if isinstance(row.get("summary"), dict)
    )
    blocked_reasons = _aggregate_reason_counts(rows, "blocked_reasons")
    anomalies = _build_anomaly_notes(rows)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start_day_utc": window.start_day_utc,
            "end_day_utc": window.end_day_utc,
            "requested_day_count": window.day_count,
            "available_day_count": len(rows),
            "missing_days": missing_days,
        },
        "summary": {
            "realized_pnl_total_usd": round(realized_total, 2),
            "latest_unrealized_pnl_usd": round(latest_unrealized, 2),
            "latest_net_paper_pnl_usd": round(latest_net, 2),
            "latest_stale_losing_review_count": latest_stale_losing_review_count,
            "stale_losing_review_count_total": stale_losing_review_total,
            "latest_max_drawdown_during_trade_pct": round(latest_max_drawdown_during_trade_pct, 3),
            "latest_max_drawdown_during_trade_symbol": (
                latest_max_drawdown_during_trade_symbol or None
            ),
            "worst_max_drawdown_during_trade_pct": round(drawdown_during_trade_worst, 3),
            "worst_open_drawdown_pct": round(drawdown_worst, 3),
            "crash_count_total": crash_total,
            "restart_count_total": restart_total,
            "data_gap_incidents_total": data_gap_total,
            "stale_data_blocks_total": stale_block_total,
        },
        "blocked_reasons_top": blocked_reasons,
        "anomaly_notes": anomalies,
        "daily_rows": rows,
    }


def write_weekly_summary(
    report: dict[str, Any],
    *,
    output_path: Path | None = None,
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    window = report.get("window", {})
    if not isinstance(window, dict):
        raise ValueError("weekly report missing window")
    start_day = str(window.get("start_day_utc") or "")
    end_day = str(window.get("end_day_utc") or "")
    if not start_day or not end_day:
        raise ValueError("weekly report missing window bounds")

    if output_path is None:
        output_path = REPORTS_DIR / f"weekly_summary_{start_day}_to_{end_day}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    latest_path = REPORTS_DIR / "weekly_summary_latest.json"
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return output_path
