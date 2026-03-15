from __future__ import annotations

import bisect
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
CONFIG_PATH = STATE_DIR / "config.json"
PAPER_STATE_PATH = STATE_DIR / "paper_state.json"
STRATEGY_STATE_PATH = STATE_DIR / "strategy_state.json"
TRADES_PATH = STATE_DIR / "trades.json"
REPORTS_DIR = STATE_DIR / "reports"
RUNTIME_EVENTS_PATH = STATE_DIR / "runtime_events.jsonl"

SNAPSHOT_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\|\s+INFO\s+\|\s+"
    r"SNAPSHOT\s+(?P<symbol>[A-Z0-9-]+)\s+\|.*?"
    r"price=(?P<price>[0-9.]+).*?"
    r"spread_bps=(?P<spread>[0-9.]+).*?"
    r"quality=(?P<quality>[a-z0-9_,-]+)"
)
BLOCKED_EXPLICIT_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\|\s+INFO\s+\|\s+"
    r"(?:(?:[A-Z0-9-]+\s+->\s+[A-Z]+\s+blocked)|(?:BUY blocked for [A-Z0-9-]+))\s+\((?P<reason>.+)\)$"
)
HOLD_REASON_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\|\s+INFO\s+\|\s+"
    r"[A-Z0-9-]+\s*(?:->|\u2192)\s*HOLD\s*\|\s*reason=(?P<reason>.+)$"
)
RESTART_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\|\s+INFO\s+\|\s+RevBot starting"
)
CRASH_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\|\s+ERROR\s+\|\s+Main loop error"
)


@dataclass(frozen=True)
class SnapshotPoint:
    ts_epoch: float
    price: float
    spread_bps: float
    quality: str
    day_utc: str


def _read_json(path: Path, default: Any):
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw) if raw.strip() else default
    except Exception:
        return default


def _to_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _to_epoch_from_log_ts(raw: str) -> float:
    dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=timezone.utc).timestamp()


def _log_paths() -> list[Path]:
    paths = [entry for entry in STATE_DIR.glob("bot.log*") if entry.is_file()]
    return sorted(paths, key=lambda item: (item.stat().st_mtime, item.name))


def _iter_log_lines():
    for path in _log_paths():
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for raw_line in handle:
                    yield raw_line.rstrip("\r\n")
        except Exception:
            continue


def _trade_day_utc(trade: dict[str, Any]) -> str | None:
    ts = _to_float(trade.get("time"), fallback=-1.0)
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def _find_latest_price(symbol: str, snapshots: dict[str, list[SnapshotPoint]]) -> float | None:
    rows = snapshots.get(symbol, [])
    if not rows:
        return None
    return rows[-1].price


def _find_min_price_since(
    symbol: str,
    entry_ts: float,
    snapshots: dict[str, list[SnapshotPoint]],
    ts_cache: dict[str, list[float]],
) -> tuple[float, float | None] | None:
    rows = snapshots.get(symbol, [])
    if not rows:
        return None

    ts_values = ts_cache.setdefault(symbol, [row.ts_epoch for row in rows])
    idx = bisect.bisect_left(ts_values, entry_ts)
    if idx >= len(rows):
        tail = rows[-1]
        return (tail.price, tail.ts_epoch)
    min_row = min(rows[idx:], key=lambda row: row.price)
    return (min_row.price, min_row.ts_epoch)


def _to_iso_utc(ts: float | None) -> str | None:
    if ts is None or ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _find_spread_bps_at_or_before(
    symbol: str,
    ts: float,
    snapshots: dict[str, list[SnapshotPoint]],
    ts_cache: dict[str, list[float]],
) -> float | None:
    rows = snapshots.get(symbol, [])
    if not rows:
        return None
    ts_values = ts_cache.setdefault(symbol, [row.ts_epoch for row in rows])
    idx = bisect.bisect_right(ts_values, ts) - 1
    if idx < 0:
        return rows[0].spread_bps
    return rows[idx].spread_bps


def _counter_to_sorted_dict(counter: dict[str, int]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def _parse_runtime_events(day_iso: str) -> dict[str, int]:
    health_check_issues = 0
    if not RUNTIME_EVENTS_PATH.exists():
        return {"health_check_issues": 0}

    try:
        with RUNTIME_EVENTS_PATH.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                event_day = str(event.get("day_utc") or "")
                if event_day != day_iso:
                    continue
                if event.get("event_type") == "health_check" and event.get("ok") is False:
                    health_check_issues += 1
    except Exception:
        return {"health_check_issues": 0}

    return {"health_check_issues": health_check_issues}


def build_daily_summary(day_iso: str) -> dict[str, Any]:
    day = date.fromisoformat(day_iso)
    day_start_dt = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    day_start = day_start_dt.timestamp()
    next_day_start = day_start + 86400.0
    next_day_start_dt = day_start_dt + timedelta(days=1)
    day_start_log_ts = day_start_dt.strftime("%Y-%m-%d %H:%M:%S")
    next_day_start_log_ts = next_day_start_dt.strftime("%Y-%m-%d %H:%M:%S")

    trades_raw = _read_json(TRADES_PATH, [])
    config_raw = _read_json(CONFIG_PATH, {})
    paper_state = _read_json(PAPER_STATE_PATH, {})
    strategy_state = _read_json(STRATEGY_STATE_PATH, {})
    trades = trades_raw if isinstance(trades_raw, list) else []
    config = config_raw if isinstance(config_raw, dict) else {}
    paper_state = paper_state if isinstance(paper_state, dict) else {}
    strategy_state = strategy_state if isinstance(strategy_state, dict) else {}
    risk_cfg = config.get("risk", {})
    if not isinstance(risk_cfg, dict):
        risk_cfg = {}

    stale_review_age_hours_threshold = max(
        _to_float(risk_cfg.get("stale_losing_review_age_hours"), fallback=36.0),
        0.0,
    )
    stale_review_unrealized_pnl_pct_threshold = min(
        _to_float(risk_cfg.get("stale_losing_review_unrealized_pnl_pct"), fallback=-10.0),
        0.0,
    )
    generated_at = datetime.now(timezone.utc)
    generated_at_epoch = generated_at.timestamp()

    day_trades = [trade for trade in trades if _trade_day_utc(trade) == day_iso]
    day_buys = [trade for trade in day_trades if str(trade.get("side", "")).upper() == "BUY"]
    day_sells = [trade for trade in day_trades if str(trade.get("side", "")).upper() == "SELL"]

    snapshots_by_symbol: dict[str, list[SnapshotPoint]] = defaultdict(list)
    snapshot_ts_cache: dict[str, list[float]] = {}
    blocked_reasons: dict[str, int] = defaultdict(int)
    hold_reasons: dict[str, int] = defaultdict(int)
    data_gap_incidents = 0
    restart_count = 0
    crash_count = 0
    positions_raw = paper_state.get("positions", {})
    positions = positions_raw if isinstance(positions_raw, dict) else {}
    snapshot_symbols = {
        str(symbol).upper()
        for symbol in positions.keys()
    } | {
        str(trade.get("symbol") or "").upper()
        for trade in day_trades
        if str(trade.get("symbol") or "").strip()
    }
    entry_times = [
        _to_float(raw_position.get("entry_time"), fallback=0.0)
        for raw_position in positions.values()
        if isinstance(raw_position, dict)
    ]
    valid_entry_times = [entry for entry in entry_times if entry > 0]
    earliest_snapshot_epoch = min([day_start, *valid_entry_times]) if valid_entry_times else day_start
    earliest_snapshot_log_ts = datetime.fromtimestamp(
        earliest_snapshot_epoch,
        tz=timezone.utc,
    ).strftime("%Y-%m-%d %H:%M:%S")

    for line in _iter_log_lines():
        if len(line) < 19:
            continue
        line_ts = line[:19]
        if (
            line_ts < earliest_snapshot_log_ts
            and line_ts < day_start_log_ts
        ):
            continue

        snapshot_match = SNAPSHOT_RE.match(line)
        if snapshot_match:
            symbol = snapshot_match.group("symbol")
            price = _to_float(snapshot_match.group("price"), fallback=0.0)
            spread = _to_float(snapshot_match.group("spread"), fallback=0.0)
            quality = snapshot_match.group("quality")
            if line_ts >= day_start_log_ts and line_ts < next_day_start_log_ts and quality != "ok":
                data_gap_incidents += 1
            if symbol not in snapshot_symbols:
                continue
            ts_epoch = _to_epoch_from_log_ts(line_ts)
            day_key = line_ts[:10]
            snapshots_by_symbol[symbol].append(
                SnapshotPoint(
                    ts_epoch=ts_epoch,
                    price=price,
                    spread_bps=spread,
                    quality=quality,
                    day_utc=day_key,
                )
            )
            continue

        blocked_match = BLOCKED_EXPLICIT_RE.match(line)
        if blocked_match:
            ts_raw = blocked_match.group("ts")
            if ts_raw >= day_start_log_ts and ts_raw < next_day_start_log_ts:
                reason = blocked_match.group("reason").strip()
                blocked_reasons[reason] += 1
            continue

        hold_match = HOLD_REASON_RE.match(line)
        if hold_match:
            ts_raw = hold_match.group("ts")
            if ts_raw >= day_start_log_ts and ts_raw < next_day_start_log_ts:
                reason = hold_match.group("reason").strip()
                hold_reasons[reason] += 1
            continue

        restart_match = RESTART_RE.match(line)
        if restart_match:
            ts_raw = restart_match.group("ts")
            if ts_raw >= day_start_log_ts and ts_raw < next_day_start_log_ts:
                restart_count += 1
            continue

        crash_match = CRASH_RE.match(line)
        if crash_match:
            ts_raw = crash_match.group("ts")
            if ts_raw >= day_start_log_ts and ts_raw < next_day_start_log_ts:
                crash_count += 1

    for rows in snapshots_by_symbol.values():
        rows.sort(key=lambda item: item.ts_epoch)

    realized_pnl = sum(_to_float(trade.get("pnl"), fallback=0.0) for trade in day_sells)
    open_positions_count = len(positions)

    unrealized_pnl = 0.0
    max_open_drawdown_pct: float | None = None
    stale_losing_review_positions: list[dict[str, Any]] = []
    max_drawdown_tracker_positions: list[dict[str, Any]] = []
    for symbol, raw_position in positions.items():
        position = raw_position if isinstance(raw_position, dict) else {}
        entry_price = _to_float(position.get("price"), fallback=0.0)
        size = _to_float(position.get("size"), fallback=0.0)
        if entry_price <= 0 or size <= 0:
            continue

        latest_price_from_snapshot = _find_latest_price(symbol, snapshots_by_symbol)
        latest_price = latest_price_from_snapshot or entry_price
        unrealized_pnl += (latest_price - entry_price) * size
        unrealized_pct = ((latest_price - entry_price) / entry_price) * 100.0

        entry_ts = _to_float(position.get("entry_time"), fallback=0.0)
        min_price_row = _find_min_price_since(
            symbol,
            entry_ts,
            snapshots_by_symbol,
            snapshot_ts_cache,
        )
        if min_price_row is None:
            min_price = latest_price
            min_price_ts = None
        else:
            min_price, min_price_ts = min_price_row
        drawdown_pct = ((min_price - entry_price) / entry_price) * 100.0
        if max_open_drawdown_pct is None or drawdown_pct < max_open_drawdown_pct:
            max_open_drawdown_pct = drawdown_pct
        advisory_max_drawdown_pct = min(drawdown_pct, 0.0)
        max_drawdown_tracker_positions.append(
            {
                "symbol": symbol,
                "max_drawdown_pct": round(advisory_max_drawdown_pct, 3),
                "entry_price": round(entry_price, 8),
                "current_price": round(latest_price, 8),
                "min_price_since_entry": round(min_price, 8),
                "entry_time": entry_ts if entry_ts > 0 else None,
                "min_price_time_utc": _to_iso_utc(min_price_ts),
            }
        )

        age_hours: float | None = None
        if entry_ts > 0:
            age_hours = max((generated_at_epoch - entry_ts) / 3600.0, 0.0)

        if (
            age_hours is not None
            and latest_price_from_snapshot is not None
            and age_hours >= stale_review_age_hours_threshold
            and unrealized_pct <= stale_review_unrealized_pnl_pct_threshold
        ):
            stale_losing_review_positions.append(
                {
                    "symbol": symbol,
                    "age_hours": round(age_hours, 2),
                    "unrealized_pnl_pct": round(unrealized_pct, 3),
                    "entry_price": round(entry_price, 8),
                    "current_price": round(latest_price_from_snapshot, 8),
                    "entry_time": entry_ts,
                }
            )

    closed_trades = [trade for trade in day_sells if "pnl" in trade]
    wins = [trade for trade in closed_trades if _to_float(trade.get("pnl"), 0.0) > 0]
    losses = [trade for trade in closed_trades if _to_float(trade.get("pnl"), 0.0) < 0]
    win_rate_pct = (len(wins) / len(closed_trades) * 100.0) if closed_trades else 0.0

    avg_closed_trade_pnl = (
        sum(_to_float(trade.get("pnl"), 0.0) for trade in closed_trades) / len(closed_trades)
        if closed_trades
        else 0.0
    )
    avg_closed_trade_gain = (
        sum(_to_float(trade.get("pnl"), 0.0) for trade in wins) / len(wins)
        if wins
        else 0.0
    )
    avg_closed_trade_loss = (
        sum(_to_float(trade.get("pnl"), 0.0) for trade in losses) / len(losses)
        if losses
        else 0.0
    )

    # Holding time: pair SELL with latest BUY for same symbol before sell.
    buy_queue: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in sorted(trades, key=lambda row: _to_float(row.get("time"), 0.0)):
        symbol = str(trade.get("symbol") or "").upper()
        side = str(trade.get("side") or "").upper()
        if not symbol:
            continue
        if side == "BUY":
            buy_queue[symbol].append(trade)
            continue
        if side == "SELL" and buy_queue[symbol]:
            buy_trade = buy_queue[symbol].pop(0)
            trade["_holding_seconds"] = max(
                0.0,
                _to_float(trade.get("time"), 0.0) - _to_float(buy_trade.get("time"), 0.0),
            )

    day_holding_seconds = [
        _to_float(trade.get("_holding_seconds"), 0.0)
        for trade in day_sells
        if "_holding_seconds" in trade
    ]
    avg_holding_seconds = (
        sum(day_holding_seconds) / len(day_holding_seconds)
        if day_holding_seconds
        else 0.0
    )

    entry_reason_counts: dict[str, int] = defaultdict(int)
    for trade in day_buys:
        reason = str(trade.get("reason") or "unknown")
        entry_reason_counts[reason] += 1

    exit_reason_counts: dict[str, int] = defaultdict(int)
    for trade in day_sells:
        reason = str(trade.get("reason") or "unknown")
        exit_reason_counts[reason] += 1

    spread_cost_estimate_usd = 0.0
    spread_samples = 0
    for trade in day_trades:
        symbol = str(trade.get("symbol") or "").upper()
        trade_ts = _to_float(trade.get("time"), fallback=0.0)
        price = _to_float(trade.get("price"), fallback=0.0)
        size = _to_float(trade.get("size"), fallback=0.0)
        if not symbol or trade_ts <= 0 or price <= 0 or size <= 0:
            continue
        spread_bps = _find_spread_bps_at_or_before(
            symbol,
            trade_ts,
            snapshots_by_symbol,
            snapshot_ts_cache,
        )
        if spread_bps is None:
            continue
        notional = price * size
        spread_cost_estimate_usd += (notional * (spread_bps / 10000.0)) / 2.0
        spread_samples += 1

    stale_data_keywords = (
        "insufficient_data",
        "warming_up_history",
        "order_book_tape_mismatch",
        "spread_too_wide",
        "stale",
    )
    stale_data_blocks = 0
    for reason, count in hold_reasons.items():
        if any(keyword in reason for keyword in stale_data_keywords):
            stale_data_blocks += count
    for reason, count in blocked_reasons.items():
        if any(keyword in reason for keyword in stale_data_keywords):
            stale_data_blocks += count

    runtime_event_counts = _parse_runtime_events(day_iso)
    health_check_issues = runtime_event_counts.get("health_check_issues", 0)

    net_paper_pnl = realized_pnl + unrealized_pnl
    stale_losing_review_positions.sort(
        key=lambda row: (float(row.get("unrealized_pnl_pct", 0.0)), str(row.get("symbol", "")))
    )
    max_drawdown_tracker_positions.sort(
        key=lambda row: (
            float(row.get("max_drawdown_pct", 0.0)),
            str(row.get("symbol", "")),
        )
    )
    worst_drawdown_position = max_drawdown_tracker_positions[0] if max_drawdown_tracker_positions else None
    report = {
        "generated_at_utc": generated_at.isoformat(),
        "day_utc": day_iso,
        "summary": {
            "total_buys": len(day_buys),
            "total_sells": len(day_sells),
            "realized_pnl_usd": round(realized_pnl, 2),
            "unrealized_pnl_usd": round(unrealized_pnl, 2),
            "net_paper_pnl_usd": round(net_paper_pnl, 2),
            "open_positions_count": open_positions_count,
            "win_rate_pct": round(win_rate_pct, 2),
            "avg_closed_trade_pnl_usd": round(avg_closed_trade_pnl, 2),
            "avg_closed_trade_gain_usd": round(avg_closed_trade_gain, 2),
            "avg_closed_trade_loss_usd": round(avg_closed_trade_loss, 2),
            "avg_holding_seconds": round(avg_holding_seconds, 2),
            "max_open_drawdown_pct": round(max_open_drawdown_pct or 0.0, 3),
            "max_drawdown_during_trade_pct": round(
                _to_float((worst_drawdown_position or {}).get("max_drawdown_pct"), 0.0),
                3,
            ),
            "max_drawdown_during_trade_symbol": (
                str((worst_drawdown_position or {}).get("symbol"))
                if worst_drawdown_position and worst_drawdown_position.get("symbol")
                else None
            ),
            "stale_losing_review_count": len(stale_losing_review_positions),
        },
        "advisory": {
            "max_drawdown_during_trade": {
                "tracked_positions_count": len(max_drawdown_tracker_positions),
                "worst_max_drawdown_pct": round(
                    _to_float((worst_drawdown_position or {}).get("max_drawdown_pct"), 0.0),
                    3,
                ),
                "worst_symbol": (
                    str((worst_drawdown_position or {}).get("symbol"))
                    if worst_drawdown_position and worst_drawdown_position.get("symbol")
                    else None
                ),
                "positions": max_drawdown_tracker_positions,
            },
            "stale_losing_review": {
                "threshold_age_hours": round(stale_review_age_hours_threshold, 2),
                "threshold_unrealized_pnl_pct": round(stale_review_unrealized_pnl_pct_threshold, 3),
                "flagged_count": len(stale_losing_review_positions),
                "flagged_symbols": [row.get("symbol") for row in stale_losing_review_positions],
                "positions": stale_losing_review_positions,
            }
        },
        "trade_reasons": {
            "entry_reasons": _counter_to_sorted_dict(entry_reason_counts),
            "exit_reasons": _counter_to_sorted_dict(exit_reason_counts),
            "blocked_reasons": _counter_to_sorted_dict(blocked_reasons),
            "hold_reasons": _counter_to_sorted_dict(hold_reasons),
        },
        "run_quality": {
            "crash_count": crash_count,
            "restart_count": restart_count,
            "stale_data_blocks": stale_data_blocks,
            "health_check_issues": health_check_issues,
            "data_gap_incidents": data_gap_incidents,
        },
        "paper_honesty": {
            "estimated_spread_cost_usd": round(spread_cost_estimate_usd, 4),
            "spread_sample_count": spread_samples,
            "estimated_slippage_penalty_usd": 0.0,
            "fill_realism_notes": (
                "Paper fills use snapshot-derived prices; spread estimate is approximate and slippage is not modeled."
            ),
        },
        "state_references": {
            "paper_state_path": str(PAPER_STATE_PATH),
            "strategy_state_path": str(STRATEGY_STATE_PATH),
            "trades_path": str(TRADES_PATH),
        },
    }
    return report


def write_daily_summary(report: dict[str, Any], *, output_path: Path | None = None) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    day_iso = str(report.get("day_utc") or "")
    if not day_iso:
        raise ValueError("Report missing day_utc")

    if output_path is None:
        output_path = REPORTS_DIR / f"daily_summary_{day_iso}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    latest_path = REPORTS_DIR / "daily_summary_latest.json"
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return output_path
