from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from utils.state_paths import resolve_state_dir

STATE_DIR = resolve_state_dir(Path(__file__).resolve().parent.parent / "state")
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


def _aggregate_volatility_opportunity(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, float]]:
    high_counts: dict[str, int] = {}
    score_totals: dict[str, float] = {}
    score_counts: dict[str, int] = {}

    for row in rows:
        advisory = row.get("advisory", {})
        if not isinstance(advisory, dict):
            continue
        radar = advisory.get("volatility_opportunity_radar", {})
        if not isinstance(radar, dict):
            continue
        symbol_rows = radar.get("symbols", [])
        if not isinstance(symbol_rows, list):
            continue

        for item in symbol_rows:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").upper()
            if not symbol:
                continue
            if bool(item.get("insufficient_data")):
                continue
            label = str(item.get("label") or "").upper()
            score = item.get("score")
            score_value = _to_float(score, fallback=float("nan"))
            if label == "HIGH":
                high_counts[symbol] = high_counts.get(symbol, 0) + 1
            if score is not None and score_value == score_value:
                score_totals[symbol] = score_totals.get(symbol, 0.0) + score_value
                score_counts[symbol] = score_counts.get(symbol, 0) + 1

    high_counts_sorted = dict(sorted(high_counts.items(), key=lambda item: (-item[1], item[0])))
    avg_scores: dict[str, float] = {}
    for symbol, total in score_totals.items():
        count = score_counts.get(symbol, 0)
        if count <= 0:
            continue
        avg_scores[symbol] = round(total / count, 3)
    avg_scores_sorted = dict(sorted(avg_scores.items(), key=lambda item: (-item[1], item[0])))
    return high_counts_sorted, avg_scores_sorted


def _aggregate_regime_route_effectiveness(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    totals: dict[str, dict[str, float]] = {}
    days_with_data = 0

    for row in rows:
        advisory = row.get("advisory", {})
        if not isinstance(advisory, dict):
            continue
        route_effectiveness = advisory.get("regime_route_effectiveness", {})
        if not isinstance(route_effectiveness, dict):
            continue
        route_rows = route_effectiveness.get("routes", {})
        if not isinstance(route_rows, dict) or not route_rows:
            continue
        days_with_data += 1

        for route, item in route_rows.items():
            if not isinstance(item, dict):
                continue
            closed = max(_to_int(item.get("closed_trades"), 0), 0)
            if closed <= 0:
                continue
            win_rate = _to_float(item.get("win_rate_pct"), 0.0)
            avg_pnl = _to_float(item.get("avg_realized_pnl_usd"), 0.0)
            avg_drawdown = item.get("avg_max_drawdown_pct")
            avg_drawdown_value = (
                _to_float(avg_drawdown, 0.0)
                if avg_drawdown is not None
                else None
            )
            bucket = totals.setdefault(
                str(route),
                {
                    "closed_trades": 0.0,
                    "wins": 0.0,
                    "pnl_total": 0.0,
                    "drawdown_total": 0.0,
                    "drawdown_count": 0.0,
                },
            )
            bucket["closed_trades"] += closed
            bucket["wins"] += closed * max(min(win_rate, 100.0), 0.0) / 100.0
            bucket["pnl_total"] += avg_pnl * closed
            if avg_drawdown_value is not None:
                bucket["drawdown_total"] += avg_drawdown_value * closed
                bucket["drawdown_count"] += closed

    routes: dict[str, Any] = {}
    best_route = None
    best_route_avg_pnl = None
    for route, bucket in sorted(totals.items(), key=lambda item: item[0]):
        closed = int(bucket.get("closed_trades", 0.0))
        if closed <= 0:
            continue
        win_rate_pct = (bucket.get("wins", 0.0) / closed) * 100.0
        avg_pnl_usd = bucket.get("pnl_total", 0.0) / closed
        drawdown_count = bucket.get("drawdown_count", 0.0)
        avg_drawdown_pct = (
            bucket.get("drawdown_total", 0.0) / drawdown_count
            if drawdown_count > 0
            else None
        )
        routes[route] = {
            "closed_trades": closed,
            "win_rate_pct": round(win_rate_pct, 3),
            "avg_realized_pnl_usd": round(avg_pnl_usd, 3),
            "avg_max_drawdown_pct": (
                round(avg_drawdown_pct, 3)
                if avg_drawdown_pct is not None
                else None
            ),
        }
        if best_route_avg_pnl is None or avg_pnl_usd > best_route_avg_pnl:
            best_route = route
            best_route_avg_pnl = avg_pnl_usd

    return {
        "days_with_data": days_with_data,
        "best_route_by_avg_pnl": best_route,
        "best_route_avg_pnl_usd": (
            round(best_route_avg_pnl, 3)
            if best_route_avg_pnl is not None
            else None
        ),
        "routes": routes,
        "note": (
            "Advisory-only weekly aggregation from daily regime-route effectiveness snapshots; "
            "execution behavior unchanged."
        ),
    }


def build_weekly_summary(
    end_day_iso: str | None = None,
    *,
    day_count: int = 7,
) -> dict[str, Any]:
    if not end_day_iso:
        end_day_iso = datetime.now(timezone.utc).date().isoformat()
    generated_at = datetime.now(timezone.utc)
    window = _day_window(end_day_iso, day_count)
    start_day_date = _parse_day(window.start_day_utc)
    end_day_date = _parse_day(window.end_day_utc)
    coverage_start_dt = datetime(
        start_day_date.year,
        start_day_date.month,
        start_day_date.day,
        tzinfo=timezone.utc,
    )
    coverage_end_dt = datetime(
        end_day_date.year,
        end_day_date.month,
        end_day_date.day,
        tzinfo=timezone.utc,
    ) + timedelta(days=1)

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
    latest_rotation_rising_count = (
        _to_int(rows[-1].get("summary", {}).get("rotation_rising_count"), 0)
        if rows and isinstance(rows[-1].get("summary"), dict)
        else 0
    )
    latest_rotation_strong_count = (
        _to_int(rows[-1].get("summary", {}).get("rotation_strong_count"), 0)
        if rows and isinstance(rows[-1].get("summary"), dict)
        else 0
    )
    latest_rotation_weakening_count = (
        _to_int(rows[-1].get("summary", {}).get("rotation_weakening_count"), 0)
        if rows and isinstance(rows[-1].get("summary"), dict)
        else 0
    )
    latest_rotation_cold_count = (
        _to_int(rows[-1].get("summary", {}).get("rotation_cold_count"), 0)
        if rows and isinstance(rows[-1].get("summary"), dict)
        else 0
    )
    latest_rotation_capital_trap_risk_count = (
        _to_int(rows[-1].get("summary", {}).get("rotation_capital_trap_risk_count"), 0)
        if rows and isinstance(rows[-1].get("summary"), dict)
        else 0
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
    latest_high_opportunity_symbol_count = (
        _to_int(rows[-1].get("summary", {}).get("symbols_flagged_high_opportunity_count"), 0)
        if rows and isinstance(rows[-1].get("summary"), dict)
        else 0
    )
    latest_best_regime_route = ""
    if rows:
        latest_row = rows[-1]
        latest_summary = latest_row.get("summary", {})
        if isinstance(latest_summary, dict):
            latest_best_regime_route = str(
                latest_summary.get("best_regime_route_by_avg_pnl") or ""
            ).strip()
        if not latest_best_regime_route:
            latest_advisory = latest_row.get("advisory", {})
            if isinstance(latest_advisory, dict):
                latest_route_effectiveness = latest_advisory.get(
                    "regime_route_effectiveness", {}
                )
                if isinstance(latest_route_effectiveness, dict):
                    latest_best_regime_route = str(
                        latest_route_effectiveness.get("best_route_by_avg_pnl") or ""
                    ).strip()
    high_signal_frequency_by_symbol, avg_opportunity_score_by_symbol = _aggregate_volatility_opportunity(rows)
    top_high_opportunity_symbols = list(high_signal_frequency_by_symbol.keys())[:5]
    regime_route_effectiveness = _aggregate_regime_route_effectiveness(rows)
    blocked_reasons = _aggregate_reason_counts(rows, "blocked_reasons")
    anomalies = _build_anomaly_notes(rows)
    coverage_end_age_hours = max(
        (generated_at - coverage_end_dt).total_seconds() / 3600.0,
        0.0,
    )
    is_fresh = coverage_end_age_hours <= 36.0

    return {
        "generated_at": generated_at.isoformat(),
        "generated_at_utc": generated_at.isoformat(),
        "coverage": {
            "window_type": "weekly",
            "start_day_utc": window.start_day_utc,
            "end_day_utc": window.end_day_utc,
            "start_utc": coverage_start_dt.isoformat(),
            "end_utc": coverage_end_dt.isoformat(),
            "requested_day_count": window.day_count,
            "available_day_count": len(rows),
        },
        "freshness": {
            "indicator": "fresh" if is_fresh else "stale",
            "is_fresh": is_fresh,
            "coverage_end_age_hours": round(coverage_end_age_hours, 3),
        },
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
            "latest_rotation_rising_count": latest_rotation_rising_count,
            "latest_rotation_strong_count": latest_rotation_strong_count,
            "latest_rotation_weakening_count": latest_rotation_weakening_count,
            "latest_rotation_cold_count": latest_rotation_cold_count,
            "latest_rotation_capital_trap_risk_count": latest_rotation_capital_trap_risk_count,
            "worst_max_drawdown_during_trade_pct": round(drawdown_during_trade_worst, 3),
            "worst_open_drawdown_pct": round(drawdown_worst, 3),
            "crash_count_total": crash_total,
            "restart_count_total": restart_total,
            "data_gap_incidents_total": data_gap_total,
            "stale_data_blocks_total": stale_block_total,
            "latest_high_opportunity_symbol_count": latest_high_opportunity_symbol_count,
            "top_high_opportunity_symbols": top_high_opportunity_symbols,
            "latest_best_regime_route_by_avg_pnl": latest_best_regime_route or None,
            "weekly_best_regime_route_by_avg_pnl": regime_route_effectiveness.get(
                "best_route_by_avg_pnl"
            ),
            "weekly_best_regime_route_avg_pnl_usd": regime_route_effectiveness.get(
                "best_route_avg_pnl_usd"
            ),
        },
        "blocked_reasons_top": blocked_reasons,
        "volatility_opportunity": {
            "high_signal_frequency_by_symbol": high_signal_frequency_by_symbol,
            "average_opportunity_score_by_symbol": avg_opportunity_score_by_symbol,
            "top_high_opportunity_symbols": top_high_opportunity_symbols,
            "note": (
                "Advisory-only aggregation from daily volatility opportunity radar; no execution behavior changes."
            ),
        },
        "regime_route_effectiveness": regime_route_effectiveness,
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
