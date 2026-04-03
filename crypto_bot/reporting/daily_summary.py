from __future__ import annotations

import bisect
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from observability.metrics import aggregate_execution_metrics
from utils.state_paths import resolve_state_dir

STATE_DIR = resolve_state_dir(Path(__file__).resolve().parent.parent / "state")
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


def _pct(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return (numerator / denominator) * 100.0


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


def _find_price_extremes_between(
    symbol: str,
    start_ts: float,
    end_ts: float,
    snapshots: dict[str, list[SnapshotPoint]],
    ts_cache: dict[str, list[float]],
) -> tuple[tuple[float, float | None] | None, tuple[float, float | None] | None]:
    rows = snapshots.get(symbol, [])
    if not rows:
        return None, None

    lower = min(start_ts, end_ts)
    upper = max(start_ts, end_ts)
    ts_values = ts_cache.setdefault(symbol, [row.ts_epoch for row in rows])
    start_idx = bisect.bisect_left(ts_values, lower)
    end_idx = bisect.bisect_right(ts_values, upper)
    window_rows = rows[start_idx:end_idx]
    if not window_rows:
        return None, None
    min_row = min(window_rows, key=lambda row: row.price)
    max_row = max(window_rows, key=lambda row: row.price)
    return (min_row.price, min_row.ts_epoch), (max_row.price, max_row.ts_epoch)


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


def _normalize_symbol(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _normalize_route_name(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in {"mean_reversion", "mean_reversion_friendly", "mr"}:
        return "mean_reversion"
    if token in {"trend_pullback", "breakout_momentum", "volatility_scalper", "observe_only"}:
        return token
    return "unknown"


def _entry_route_from_reason(reason: Any) -> str:
    raw = str(reason or "").strip().lower()
    if "trend_pullback" in raw:
        return "trend_pullback"
    if "breakout_momentum" in raw:
        return "breakout_momentum"
    if "volatility_scalper" in raw or raw.startswith("scalper_"):
        return "volatility_scalper"
    if raw == "observe_only_mode":
        return "observe_only"
    if not raw:
        return "unknown"
    return "mean_reversion"


def _entry_route_from_position(position: dict[str, Any]) -> str:
    for key in ("entry_route", "effective_route", "entry_strategy", "effective_strategy", "strategy"):
        route = _normalize_route_name(position.get(key))
        if route != "unknown":
            return route
    return _entry_route_from_reason(position.get("reason"))


def _build_regime_route_effectiveness(
    day_buys: list[dict[str, Any]],
    day_sells: list[dict[str, Any]],
) -> dict[str, Any]:
    buy_queue_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in sorted(day_buys, key=lambda row: _to_float(row.get("time"), 0.0)):
        symbol = _normalize_symbol(trade.get("symbol"))
        trade_ts = _to_float(trade.get("time"), fallback=0.0)
        if not symbol or trade_ts <= 0:
            continue
        buy_queue_by_symbol[symbol].append(
            {
                "time": trade_ts,
                "price": _to_float(trade.get("price"), fallback=0.0),
                "route": _entry_route_from_reason(trade.get("reason")),
            }
        )

    route_rows: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {
            "pnl_usd": [],
            "hold_hours": [],
            "drawdown_pct": [],
            "wins": [],
        }
    )

    for sell_trade in sorted(day_sells, key=lambda row: _to_float(row.get("time"), 0.0)):
        symbol = _normalize_symbol(sell_trade.get("symbol"))
        exit_ts = _to_float(sell_trade.get("time"), fallback=0.0)
        if not symbol or exit_ts <= 0:
            continue
        matched_buy = None
        if buy_queue_by_symbol[symbol]:
            matched_buy = buy_queue_by_symbol[symbol].pop(0)

        route = _entry_route_from_reason((matched_buy or {}).get("route"))
        if route == "mean_reversion":
            route = _entry_route_from_reason((matched_buy or {}).get("route") or sell_trade.get("reason"))
        pnl_usd = _to_float(sell_trade.get("pnl"), fallback=0.0)
        entry_price = _to_float((matched_buy or {}).get("price"), fallback=0.0)
        exit_price = _to_float(sell_trade.get("price"), fallback=0.0)
        pnl_pct = None
        if entry_price > 0 and exit_price > 0:
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100.0
        drawdown_pct = min(pnl_pct or 0.0, 0.0)

        route_rows[route]["pnl_usd"].append(pnl_usd)
        route_rows[route]["drawdown_pct"].append(drawdown_pct)
        route_rows[route]["wins"].append(1.0 if pnl_usd > 0 else 0.0)
        if matched_buy:
            hold_hours = max((exit_ts - _to_float(matched_buy.get("time"), 0.0)) / 3600.0, 0.0)
            route_rows[route]["hold_hours"].append(hold_hours)

    routes: dict[str, Any] = {}
    total_closed_trades = 0
    best_route = None
    best_route_avg_pnl = None
    for route, values in sorted(route_rows.items(), key=lambda item: item[0]):
        closed_count = len(values["pnl_usd"])
        if closed_count <= 0:
            continue
        total_closed_trades += closed_count
        avg_realized_pnl_usd = _avg(values["pnl_usd"])
        win_rate_pct = (_avg(values["wins"]) or 0.0) * 100.0
        avg_hold_hours = _avg(values["hold_hours"])
        avg_max_drawdown_pct = _avg(values["drawdown_pct"])
        routes[route] = {
            "closed_trades": closed_count,
            "win_rate_pct": round(win_rate_pct, 3),
            "avg_realized_pnl_usd": round(_to_float(avg_realized_pnl_usd, 0.0), 3),
            "avg_hold_hours": (
                round(_to_float(avg_hold_hours, 0.0), 3)
                if avg_hold_hours is not None
                else None
            ),
            "avg_max_drawdown_pct": (
                round(_to_float(avg_max_drawdown_pct, 0.0), 3)
                if avg_max_drawdown_pct is not None
                else None
            ),
        }
        if best_route_avg_pnl is None or _to_float(avg_realized_pnl_usd, 0.0) > best_route_avg_pnl:
            best_route_avg_pnl = _to_float(avg_realized_pnl_usd, 0.0)
            best_route = route

    return {
        "total_closed_trades": total_closed_trades,
        "best_route_by_avg_pnl": best_route,
        "best_route_avg_pnl_usd": (
            round(_to_float(best_route_avg_pnl, 0.0), 3)
            if best_route_avg_pnl is not None
            else None
        ),
        "routes": routes,
        "note": (
            "Advisory-only regime-route effectiveness derived from same-day BUY/SELL pairings; "
            "does not change strategy or execution."
        ),
    }


def _build_capital_lockup_by_route(
    *,
    positions: dict[str, Any],
    snapshots_by_symbol: dict[str, list[SnapshotPoint]],
    generated_at_epoch: float,
    stale_age_hours_threshold: float,
) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "open_positions": 0,
            "total_notional_usd": 0.0,
            "age_hours_values": [],
            "age_weighted_sum": 0.0,
            "age_weighted_notional": 0.0,
            "stale_age_count": 0,
            "symbols": [],
        }
    )

    for raw_symbol, raw_position in positions.items():
        symbol = _normalize_symbol(raw_symbol)
        position = raw_position if isinstance(raw_position, dict) else {}
        entry_price = _to_float(position.get("price"), fallback=0.0)
        size = _to_float(position.get("size"), fallback=0.0)
        if not symbol or entry_price <= 0 or size <= 0:
            continue

        latest_price = _find_latest_price(symbol, snapshots_by_symbol) or entry_price
        notional_usd = max(latest_price * size, 0.0)
        route = _entry_route_from_position(position)
        bucket = buckets[route]
        bucket["open_positions"] += 1
        bucket["total_notional_usd"] += notional_usd
        bucket["symbols"].append(symbol)

        entry_ts = _to_float(position.get("entry_time"), fallback=0.0)
        if entry_ts <= 0:
            continue
        age_hours = max((generated_at_epoch - entry_ts) / 3600.0, 0.0)
        bucket["age_hours_values"].append(age_hours)
        bucket["age_weighted_sum"] += age_hours * notional_usd
        bucket["age_weighted_notional"] += notional_usd
        if age_hours >= stale_age_hours_threshold:
            bucket["stale_age_count"] += 1

    rows: list[dict[str, Any]] = []
    total_notional_usd = 0.0
    overall_weighted_sum = 0.0
    overall_weighted_notional = 0.0
    total_open_positions = 0
    total_stale_age_positions = 0
    for route, bucket in sorted(buckets.items(), key=lambda item: item[0]):
        ages = [float(value) for value in bucket["age_hours_values"]]
        total_notional = float(bucket["total_notional_usd"])
        weighted_notional = float(bucket["age_weighted_notional"])
        weighted_age = (
            float(bucket["age_weighted_sum"]) / weighted_notional
            if weighted_notional > 0
            else None
        )
        total_notional_usd += total_notional
        total_open_positions += int(bucket["open_positions"])
        total_stale_age_positions += int(bucket["stale_age_count"])
        overall_weighted_sum += float(bucket["age_weighted_sum"])
        overall_weighted_notional += weighted_notional
        rows.append(
            {
                "route": route,
                "open_positions": int(bucket["open_positions"]),
                "total_notional_usd": round(total_notional, 3),
                "avg_age_hours": (
                    round(_to_float(_avg(ages), 0.0), 3)
                    if ages
                    else None
                ),
                "median_age_hours": (
                    round(_to_float(_median(ages), 0.0), 3)
                    if ages
                    else None
                ),
                "weighted_age_hours": (
                    round(_to_float(weighted_age, 0.0), 3)
                    if weighted_age is not None
                    else None
                ),
                "oldest_age_hours": (
                    round(max(ages), 3)
                    if ages
                    else None
                ),
                "stale_age_count": int(bucket["stale_age_count"]),
                "symbols": sorted(set(str(symbol) for symbol in bucket["symbols"])),
            }
        )

    rows.sort(
        key=lambda row: (
            -_to_float(row.get("weighted_age_hours"), fallback=-1.0),
            -_to_float(row.get("total_notional_usd"), fallback=0.0),
            str(row.get("route") or ""),
        )
    )
    overall_weighted_age_hours = (
        overall_weighted_sum / overall_weighted_notional
        if overall_weighted_notional > 0
        else None
    )
    return {
        "stale_age_hours_threshold": round(stale_age_hours_threshold, 3),
        "total_open_positions": total_open_positions,
        "total_notional_usd": round(total_notional_usd, 3),
        "total_stale_age_positions": total_stale_age_positions,
        "overall_weighted_age_hours": (
            round(overall_weighted_age_hours, 3)
            if overall_weighted_age_hours is not None
            else None
        ),
        "routes": rows,
    }


def _build_closed_trades_by_symbol(
    trades: list[dict[str, Any]],
    stale_review_age_hours_threshold: float,
    stale_review_unrealized_pnl_pct_threshold: float,
) -> dict[str, list[dict[str, Any]]]:
    closed_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    buy_queue_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sorted_trades = sorted(trades, key=lambda row: _to_float(row.get("time"), 0.0))

    for idx, trade in enumerate(sorted_trades):
        symbol = _normalize_symbol(trade.get("symbol"))
        side = str(trade.get("side") or "").upper()
        trade_ts = _to_float(trade.get("time"), fallback=0.0)
        if not symbol or trade_ts <= 0:
            continue

        if side == "BUY":
            buy_queue_by_symbol[symbol].append(trade)
            continue
        if side != "SELL":
            continue

        matched_buy = None
        if buy_queue_by_symbol[symbol]:
            matched_buy = buy_queue_by_symbol[symbol].pop(0)

        entry_price = _to_float((matched_buy or {}).get("price"), fallback=0.0) if matched_buy else 0.0
        exit_price = _to_float(trade.get("price"), fallback=0.0)
        entry_ts = _to_float((matched_buy or {}).get("time"), fallback=0.0) if matched_buy else 0.0
        hold_hours = None
        if entry_ts > 0:
            hold_hours = max((trade_ts - entry_ts) / 3600.0, 0.0)
        pnl_usd = _to_float(trade.get("pnl"), fallback=0.0)
        pnl_pct = None
        if entry_price > 0 and exit_price > 0:
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100.0
        stale_review_hit = (
            hold_hours is not None
            and pnl_pct is not None
            and hold_hours >= stale_review_age_hours_threshold
            and pnl_pct <= stale_review_unrealized_pnl_pct_threshold
        )
        max_drawdown_pct = min(pnl_pct or 0.0, 0.0)

        closed_by_symbol[symbol].append(
            {
                "trade_id": f"{symbol}:{trade_ts}:{idx}",
                "symbol": symbol,
                "entry_time": entry_ts if entry_ts > 0 else None,
                "exit_time": trade_ts,
                "hold_hours": hold_hours,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "stale_review_hit": stale_review_hit,
                "max_drawdown_pct": max_drawdown_pct,
            }
        )

    for rows in closed_by_symbol.values():
        rows.sort(key=lambda row: float(row.get("exit_time") or 0.0), reverse=True)
    return closed_by_symbol


def _route_from_trade_row(trade: dict[str, Any]) -> str:
    for key in ("effective_route", "entry_route", "route", "effective_strategy", "strategy"):
        route = _normalize_route_name(trade.get(key))
        if route != "unknown":
            return route
    return _entry_route_from_reason(trade.get("reason"))


def _build_closed_trade_mae_mfe_by_route(
    *,
    trades: list[dict[str, Any]],
    day_start_ts: float,
    day_end_ts: float,
    snapshots_by_symbol: dict[str, list[SnapshotPoint]],
    snapshot_ts_cache: dict[str, list[float]],
) -> dict[str, Any]:
    buy_queue_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    route_rows: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "sample_count": 0,
            "mae_pct_values": [],
            "mfe_pct_values": [],
            "capture_pct_values": [],
            "hold_hours_values": [],
            "fallback_without_snapshot_count": 0,
        }
    )
    sample_events: list[dict[str, Any]] = []

    for trade in sorted(trades, key=lambda row: _to_float(row.get("time"), 0.0)):
        symbol = _normalize_symbol(trade.get("symbol"))
        side = str(trade.get("side") or "").strip().upper()
        ts = _to_float(trade.get("time"), fallback=0.0)
        if not symbol or ts <= 0:
            continue

        if side == "BUY":
            buy_queue_by_symbol[symbol].append(trade)
            continue
        if side != "SELL":
            continue

        matched_buy = None
        if buy_queue_by_symbol[symbol]:
            matched_buy = buy_queue_by_symbol[symbol].pop(0)
        if not (day_start_ts <= ts < day_end_ts):
            continue

        entry_price = _to_float((matched_buy or {}).get("price"), fallback=0.0)
        entry_ts = _to_float((matched_buy or {}).get("time"), fallback=0.0)
        exit_price = _to_float(trade.get("price"), fallback=0.0)
        if entry_price <= 0 or exit_price <= 0:
            continue

        route = _route_from_trade_row(matched_buy or trade)
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100.0
        min_row, max_row = _find_price_extremes_between(
            symbol,
            entry_ts if entry_ts > 0 else ts,
            ts,
            snapshots_by_symbol,
            snapshot_ts_cache,
        )
        used_fallback = False
        if min_row is None or max_row is None:
            used_fallback = True
            min_price = min(entry_price, exit_price)
            max_price = max(entry_price, exit_price)
            min_ts = entry_ts if entry_price <= exit_price else ts
            max_ts = ts if exit_price >= entry_price else entry_ts
        else:
            min_price, min_ts = min_row
            max_price, max_ts = max_row

        mae_pct = min(((min_price - entry_price) / entry_price) * 100.0, 0.0)
        mfe_pct = max(((max_price - entry_price) / entry_price) * 100.0, 0.0)
        capture_pct = None
        if mfe_pct > 0:
            capture_pct = max(min((pnl_pct / mfe_pct) * 100.0, 150.0), -150.0)

        route_bucket = route_rows[route]
        route_bucket["sample_count"] += 1
        route_bucket["mae_pct_values"].append(mae_pct)
        route_bucket["mfe_pct_values"].append(mfe_pct)
        if capture_pct is not None:
            route_bucket["capture_pct_values"].append(capture_pct)
        if entry_ts > 0:
            route_bucket["hold_hours_values"].append(max((ts - entry_ts) / 3600.0, 0.0))
        if used_fallback:
            route_bucket["fallback_without_snapshot_count"] += 1

        sample_events.append(
            {
                "symbol": symbol,
                "route": route,
                "entry_ts": entry_ts if entry_ts > 0 else None,
                "exit_ts": ts,
                "entry_price": round(entry_price, 8),
                "exit_price": round(exit_price, 8),
                "mae_pct": round(mae_pct, 4),
                "mfe_pct": round(mfe_pct, 4),
                "capture_pct": round(capture_pct, 4) if capture_pct is not None else None,
                "min_price_observed": round(min_price, 8),
                "max_price_observed": round(max_price, 8),
                "min_price_time_utc": _to_iso_utc(min_ts),
                "max_price_time_utc": _to_iso_utc(max_ts),
                "fallback_without_snapshot": bool(used_fallback),
            }
        )

    routes: dict[str, Any] = {}
    for route, bucket in sorted(route_rows.items(), key=lambda item: item[0]):
        sample_count = int(bucket.get("sample_count", 0) or 0)
        if sample_count <= 0:
            continue
        mae_values = [float(v) for v in bucket.get("mae_pct_values", [])]
        mfe_values = [float(v) for v in bucket.get("mfe_pct_values", [])]
        capture_values = [float(v) for v in bucket.get("capture_pct_values", [])]
        hold_values = [float(v) for v in bucket.get("hold_hours_values", [])]
        routes[route] = {
            "sample_count": sample_count,
            "avg_mae_pct": round(_to_float(_avg(mae_values), 0.0), 4) if mae_values else None,
            "median_mae_pct": round(_to_float(_median(mae_values), 0.0), 4) if mae_values else None,
            "avg_mfe_pct": round(_to_float(_avg(mfe_values), 0.0), 4) if mfe_values else None,
            "median_mfe_pct": round(_to_float(_median(mfe_values), 0.0), 4) if mfe_values else None,
            "avg_capture_pct": (
                round(_to_float(_avg(capture_values), 0.0), 4)
                if capture_values
                else None
            ),
            "median_capture_pct": (
                round(_to_float(_median(capture_values), 0.0), 4)
                if capture_values
                else None
            ),
            "avg_hold_hours": (
                round(_to_float(_avg(hold_values), 0.0), 3)
                if hold_values
                else None
            ),
            "fallback_without_snapshot_count": int(bucket.get("fallback_without_snapshot_count", 0) or 0),
        }

    sample_events.sort(key=lambda row: _to_float(row.get("exit_ts"), 0.0), reverse=True)
    return {
        "sample_count": sum(int(row.get("sample_count", 0) or 0) for row in routes.values()),
        "routes": routes,
        "events": sample_events[:25],
        "note": (
            "Advisory-only MAE/MFE approximation from available snapshot history between entry and exit; "
            "falls back to entry/exit bounds when intra-trade snapshots are unavailable."
        ),
    }


def _stale_release_redeploy_attribution(
    trades: list[dict[str, Any]],
    *,
    stale_exit_start_ts: float | None = None,
    stale_exit_end_ts: float | None = None,
) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda item: _to_float(item.get("time"), 0.0))
    stale_indices: list[int] = []
    for idx, row in enumerate(ordered):
        if str(row.get("side") or "").strip().upper() != "SELL":
            continue
        if str(row.get("reason") or "").strip() != "stale_position_risk_release":
            continue
        ts = _to_float(row.get("time"), 0.0)
        if ts <= 0:
            continue
        if stale_exit_start_ts is not None and ts < stale_exit_start_ts:
            continue
        if stale_exit_end_ts is not None and ts >= stale_exit_end_ts:
            continue
        stale_indices.append(idx)

    if not stale_indices:
        return {
            "stale_release_exits": 0,
            "redeployed": 0,
            "redeploy_rate_pct": 0.0,
            "closed_after_redeploy": 0,
            "close_rate_after_redeploy_pct": 0.0,
            "win_rate_after_redeploy_pct": 0.0,
            "median_redeploy_delay_minutes": None,
            "median_close_delay_hours": None,
            "median_redeploy_pnl_pct": None,
            "route_stats": {},
            "latest_events": [],
        }

    route_stats: dict[str, dict[str, Any]] = {}
    redeployed = 0
    closed_after_redeploy = 0
    wins = 0
    redeploy_delays: list[float] = []
    close_delays: list[float] = []
    redeploy_pnl_pcts: list[float] = []
    events: list[dict[str, Any]] = []

    for idx in stale_indices:
        stale_row = ordered[idx]
        symbol = _normalize_symbol(stale_row.get("symbol"))
        stale_ts = _to_float(stale_row.get("time"), 0.0)
        stale_price = _to_float(stale_row.get("price"), 0.0)
        stale_size = _to_float(stale_row.get("size"), 0.0)
        if not symbol:
            continue

        event: dict[str, Any] = {
            "symbol": symbol,
            "stale_exit_ts": stale_ts,
            "stale_exit_price": stale_price,
            "stale_exit_size": stale_size,
            "redeployed": False,
            "closed_after_redeploy": False,
        }

        next_buy_idx: int | None = None
        next_buy: dict[str, Any] | None = None
        for j in range(idx + 1, len(ordered)):
            row = ordered[j]
            if _normalize_symbol(row.get("symbol")) != symbol:
                continue
            if str(row.get("side") or "").strip().upper() == "BUY":
                next_buy = row
                next_buy_idx = j
                break

        if next_buy is None or next_buy_idx is None:
            events.append(event)
            continue

        buy_ts = _to_float(next_buy.get("time"), 0.0)
        buy_price = _to_float(next_buy.get("price"), 0.0)
        buy_size = _to_float(next_buy.get("size"), 0.0)
        route = _route_from_trade_row(next_buy)
        event["redeployed"] = True
        event["redeploy_ts"] = buy_ts
        event["redeploy_price"] = buy_price
        event["redeploy_size"] = buy_size
        event["redeploy_route"] = route
        redeployed += 1
        if stale_ts > 0 and buy_ts > stale_ts:
            delay_minutes = (buy_ts - stale_ts) / 60.0
            event["redeploy_delay_minutes"] = round(delay_minutes, 3)
            redeploy_delays.append(delay_minutes)

        route_bucket = route_stats.setdefault(
            route,
            {
                "stale_release_exits": 0,
                "redeployed": 0,
                "closed_after_redeploy": 0,
                "wins": 0,
                "redeploy_delay_minutes_values": [],
                "close_delay_hours_values": [],
                "redeploy_pnl_pct_values": [],
            },
        )
        route_bucket["stale_release_exits"] += 1
        route_bucket["redeployed"] += 1
        if event.get("redeploy_delay_minutes") is not None:
            route_bucket["redeploy_delay_minutes_values"].append(
                _to_float(event.get("redeploy_delay_minutes"), 0.0)
            )

        close_row: dict[str, Any] | None = None
        for k in range(next_buy_idx + 1, len(ordered)):
            row = ordered[k]
            if _normalize_symbol(row.get("symbol")) != symbol:
                continue
            if str(row.get("side") or "").strip().upper() == "SELL":
                close_row = row
                break
        if close_row is None:
            events.append(event)
            continue

        close_ts = _to_float(close_row.get("time"), 0.0)
        close_price = _to_float(close_row.get("price"), 0.0)
        close_reason = str(close_row.get("reason") or "")
        close_delay_hours = ((close_ts - buy_ts) / 3600.0) if close_ts > buy_ts > 0 else 0.0
        pnl_pct = ((close_price - buy_price) / buy_price) * 100.0 if buy_price > 0 else 0.0

        event["closed_after_redeploy"] = True
        event["close_ts"] = close_ts
        event["close_price"] = close_price
        event["close_reason"] = close_reason
        event["close_delay_hours"] = round(close_delay_hours, 3)
        event["redeploy_pnl_pct"] = round(pnl_pct, 4)
        event["redeploy_outcome"] = "win" if pnl_pct > 0 else ("loss" if pnl_pct < 0 else "flat")
        closed_after_redeploy += 1
        close_delays.append(close_delay_hours)
        redeploy_pnl_pcts.append(pnl_pct)
        route_bucket["closed_after_redeploy"] += 1
        route_bucket["close_delay_hours_values"].append(close_delay_hours)
        route_bucket["redeploy_pnl_pct_values"].append(pnl_pct)
        if pnl_pct > 0:
            wins += 1
            route_bucket["wins"] += 1
        events.append(event)

    route_summary: dict[str, Any] = {}
    for route, row in route_stats.items():
        stale_release_exits = int(row.get("stale_release_exits", 0) or 0)
        redeploy_count = int(row.get("redeployed", 0) or 0)
        closed_count = int(row.get("closed_after_redeploy", 0) or 0)
        route_wins = int(row.get("wins", 0) or 0)
        route_summary[route] = {
            "stale_release_exits": stale_release_exits,
            "redeployed": redeploy_count,
            "closed_after_redeploy": closed_count,
            "redeploy_rate_pct": round(_pct(redeploy_count, max(stale_release_exits, 1)), 2),
            "close_rate_after_redeploy_pct": round(_pct(closed_count, max(redeploy_count, 1)), 2),
            "win_rate_after_redeploy_pct": round(_pct(route_wins, max(closed_count, 1)), 2),
            "median_redeploy_delay_minutes": _median(
                [float(v) for v in row.get("redeploy_delay_minutes_values", [])]
            ),
            "median_close_delay_hours": _median(
                [float(v) for v in row.get("close_delay_hours_values", [])]
            ),
            "median_redeploy_pnl_pct": _median(
                [float(v) for v in row.get("redeploy_pnl_pct_values", [])]
            ),
        }

    events.sort(key=lambda item: _to_float(item.get("stale_exit_ts"), 0.0), reverse=True)
    stale_release_exits_total = len(stale_indices)
    return {
        "stale_release_exits": stale_release_exits_total,
        "redeployed": redeployed,
        "redeploy_rate_pct": round(_pct(redeployed, max(stale_release_exits_total, 1)), 2),
        "closed_after_redeploy": closed_after_redeploy,
        "close_rate_after_redeploy_pct": round(_pct(closed_after_redeploy, max(redeployed, 1)), 2),
        "win_rate_after_redeploy_pct": round(_pct(wins, max(closed_after_redeploy, 1)), 2),
        "median_redeploy_delay_minutes": _median(redeploy_delays),
        "median_close_delay_hours": _median(close_delays),
        "median_redeploy_pnl_pct": _median(redeploy_pnl_pcts),
        "route_stats": dict(sorted(route_summary.items(), key=lambda item: item[0])),
        "latest_events": events[:25],
    }


def _select_rotation_window_rows(
    rows: list[dict[str, Any]],
    now_epoch: float,
    day_window: int,
    trade_window: int,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    cutoff = now_epoch - (max(day_window, 1) * 86400.0)
    by_days = [row for row in rows if _to_float(row.get("exit_time"), 0.0) >= cutoff]
    by_trades = rows[: max(1, int(trade_window))]
    dedup: dict[str, dict[str, Any]] = {}
    for row in by_days:
        dedup[str(row.get("trade_id") or "")] = row
    for row in by_trades:
        dedup[str(row.get("trade_id") or "")] = row
    out = list(dedup.values())
    out.sort(key=lambda row: _to_float(row.get("exit_time"), 0.0), reverse=True)
    return out


def _compute_rotation_window_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "closed_trade_count": 0,
            "win_rate_pct": None,
            "avg_realized_pnl_usd": None,
            "avg_realized_pnl_pct": None,
            "avg_hold_hours": None,
            "avg_recovery_hours": None,
            "stale_review_frequency_pct": None,
            "avg_max_drawdown_pct": None,
        }

    wins = [row for row in rows if _to_float(row.get("pnl_usd"), 0.0) > 0]
    pnl_usd_values = [_to_float(row.get("pnl_usd"), 0.0) for row in rows]
    pnl_pct_values = [
        _to_float(row.get("pnl_pct"), 0.0)
        for row in rows
        if row.get("pnl_pct") is not None
    ]
    hold_values = [
        _to_float(row.get("hold_hours"), 0.0)
        for row in rows
        if row.get("hold_hours") is not None
    ]
    recovery_values = [
        _to_float(row.get("hold_hours"), 0.0)
        for row in rows
        if _to_float(row.get("pnl_usd"), 0.0) > 0 and row.get("hold_hours") is not None
    ]
    stale_hits = sum(1 for row in rows if bool(row.get("stale_review_hit")))
    drawdown_values = [
        _to_float(row.get("max_drawdown_pct"), 0.0)
        for row in rows
    ]

    return {
        "closed_trade_count": len(rows),
        "win_rate_pct": (len(wins) / len(rows)) * 100.0,
        "avg_realized_pnl_usd": _avg(pnl_usd_values),
        "avg_realized_pnl_pct": _avg(pnl_pct_values),
        "avg_hold_hours": _avg(hold_values),
        "avg_recovery_hours": _avg(recovery_values),
        "stale_review_frequency_pct": (stale_hits / len(rows)) * 100.0,
        "avg_max_drawdown_pct": _avg(drawdown_values),
    }


def _compute_rotation_score(metrics: dict[str, Any]) -> float | None:
    trade_count = int(metrics.get("closed_trade_count") or 0)
    win_rate = metrics.get("win_rate_pct")
    if trade_count <= 0 or win_rate is None:
        return None

    win_norm = max(0.0, min(1.0, _to_float(win_rate, 0.0) / 100.0))
    pnl_norm = max(0.0, min(1.0, (_to_float(metrics.get("avg_realized_pnl_pct"), 0.0) + 6.0) / 12.0))
    avg_hold = metrics.get("avg_hold_hours")
    hold_norm = 0.5 if avg_hold is None else max(0.0, min(1.0, 1.0 - (_to_float(avg_hold, 0.0) / 72.0)))
    avg_recovery = metrics.get("avg_recovery_hours")
    recovery_norm = hold_norm if avg_recovery is None else max(0.0, min(1.0, 1.0 - (_to_float(avg_recovery, 0.0) / 96.0)))
    stale_penalty = max(
        0.0,
        min(1.0, _to_float(metrics.get("stale_review_frequency_pct"), 0.0) / 100.0),
    )
    drawdown_penalty = max(
        0.0,
        min(1.0, abs(min(_to_float(metrics.get("avg_max_drawdown_pct"), 0.0), 0.0)) / 15.0),
    )
    base = (
        (0.35 * win_norm)
        + (0.30 * pnl_norm)
        + (0.15 * hold_norm)
        + (0.10 * recovery_norm)
        + (0.10 * (1.0 - stale_penalty))
    )
    score = (base - (0.15 * drawdown_penalty)) * 100.0
    return max(0.0, min(100.0, score))


def _rotation_status(
    short_score: float | None,
    medium_score: float | None,
    delta: float | None,
    short_metrics: dict[str, Any],
    medium_metrics: dict[str, Any],
) -> str:
    short = short_score if short_score is not None else (medium_score if medium_score is not None else 50.0)
    medium = medium_score if medium_score is not None else (short_score if short_score is not None else 50.0)
    rotation_delta = delta if delta is not None else 0.0
    stale_frequency = short_metrics.get("stale_review_frequency_pct")
    if stale_frequency is None:
        stale_frequency = medium_metrics.get("stale_review_frequency_pct")
    stale_frequency = _to_float(stale_frequency, 0.0)
    drawdown = short_metrics.get("avg_max_drawdown_pct")
    if drawdown is None:
        drawdown = medium_metrics.get("avg_max_drawdown_pct")
    drawdown = _to_float(drawdown, 0.0)

    if short < 35.0 and medium < 40.0 and stale_frequency >= 30.0 and drawdown <= -8.0:
        return "Capital Trap Risk"
    if short >= 68.0 and medium >= 60.0 and rotation_delta >= 6.0:
        return "Rising"
    if short >= 65.0 and medium >= 65.0 and abs(rotation_delta) <= 6.0:
        return "Strong"
    if short <= 32.0 and medium <= 40.0 and rotation_delta <= -6.0:
        return "Cold"
    if rotation_delta <= -8.0 or (short < medium and short < 52.0):
        return "Weakening"
    return "Neutral"


def _build_symbol_rotation_rows(
    symbols: set[str],
    closed_by_symbol: dict[str, list[dict[str, Any]]],
    now_epoch: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol in sorted(symbols):
        closed_rows = closed_by_symbol.get(symbol, [])
        short_rows = _select_rotation_window_rows(closed_rows, now_epoch, 7, 10)
        medium_rows = _select_rotation_window_rows(closed_rows, now_epoch, 30, 30)
        short_metrics = _compute_rotation_window_metrics(short_rows)
        medium_metrics = _compute_rotation_window_metrics(medium_rows)
        short_score = _compute_rotation_score(short_metrics)
        medium_score = _compute_rotation_score(medium_metrics)
        rotation_delta = (
            (short_score - medium_score)
            if short_score is not None and medium_score is not None
            else None
        )
        status = _rotation_status(
            short_score,
            medium_score,
            rotation_delta,
            short_metrics,
            medium_metrics,
        )
        rows.append(
            {
                "symbol": symbol,
                "short_term_score": round(short_score, 3) if short_score is not None else None,
                "medium_term_score": round(medium_score, 3) if medium_score is not None else None,
                "rotation_delta": round(rotation_delta, 3) if rotation_delta is not None else None,
                "status": status,
                "short_window_metrics": short_metrics,
                "medium_window_metrics": medium_metrics,
            }
        )
    return rows


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return max(variance, 0.0) ** 0.5


def _select_rows_within_window(
    rows: list[SnapshotPoint],
    end_ts: float,
    window_seconds: float,
) -> list[SnapshotPoint]:
    cutoff = end_ts - max(window_seconds, 0.0)
    return [row for row in rows if row.ts_epoch >= cutoff and row.ts_epoch <= end_ts]


def _opportunity_label(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 70.0:
        return "HIGH"
    if score >= 40.0:
        return "MEDIUM"
    return "LOW"


def _build_opportunity_reason(
    stretch_score: float,
    volatility_spike_score: float,
    bounce_context_score: float,
    liquidity_quality_score: float | None,
) -> str:
    parts: list[str] = []
    if stretch_score >= 70.0:
        parts.append("Deep stretch below short-term mean")
    elif stretch_score >= 45.0:
        parts.append("Moderate stretch below short-term mean")
    else:
        parts.append("Mild stretch profile")

    if volatility_spike_score >= 70.0:
        parts.append("with elevated short-term volatility")
    elif volatility_spike_score >= 40.0:
        parts.append("with moderate volatility expansion")
    else:
        parts.append("with limited volatility expansion")

    if bounce_context_score >= 65.0:
        parts.append("and improving bounce context near local lows")
    elif bounce_context_score < 35.0:
        parts.append("but weak bounce context (slow-bleed risk)")

    if liquidity_quality_score is not None and liquidity_quality_score < 35.0:
        parts.append("Liquidity/spread quality is weak, so caution is advised.")

    return " ".join(parts).strip()


def _build_symbol_volatility_opportunity(
    symbol: str,
    rows: list[SnapshotPoint],
) -> dict[str, Any]:
    sorted_rows = sorted(rows, key=lambda row: row.ts_epoch)
    if len(sorted_rows) < 10:
        return {
            "symbol": symbol,
            "score": None,
            "label": None,
            "reason": "Insufficient data for volatility opportunity scoring.",
            "confidence_label": "LOW",
            "stretch_score": None,
            "volatility_spike_score": None,
            "bounce_context_score": None,
            "liquidity_quality_score": None,
            "observed_history_span_minutes": (
                round(max((sorted_rows[-1].ts_epoch - sorted_rows[0].ts_epoch) / 60.0, 0.0), 3)
                if len(sorted_rows) >= 2
                else 0.0
            ),
            "observed_point_count": len(sorted_rows),
            "insufficient_data": True,
            "insufficient_reason_code": "insufficient_point_count",
            "insufficient_reason_message": (
                f"Observed {len(sorted_rows)} points, need at least 10 for radar."
            ),
        }

    latest = sorted_rows[-1]
    earliest = sorted_rows[0]
    now_epoch = latest.ts_epoch
    observed_span_minutes = max((latest.ts_epoch - earliest.ts_epoch) / 60.0, 0.0)
    if observed_span_minutes < 20.0:
        return {
            "symbol": symbol,
            "score": None,
            "label": None,
            "reason": "Insufficient data for volatility opportunity scoring.",
            "confidence_label": "LOW",
            "stretch_score": None,
            "volatility_spike_score": None,
            "bounce_context_score": None,
            "liquidity_quality_score": None,
            "observed_history_span_minutes": round(observed_span_minutes, 3),
            "observed_point_count": len(sorted_rows),
            "insufficient_data": True,
            "insufficient_reason_code": "insufficient_history_span",
            "insufficient_reason_message": (
                f"Observed span {observed_span_minutes:.1f}m is below 20m minimum."
            ),
        }

    rows_30m = _select_rows_within_window(sorted_rows, now_epoch, 30 * 60)
    rows_1h = _select_rows_within_window(sorted_rows, now_epoch, 60 * 60)
    rows_8h = _select_rows_within_window(sorted_rows, now_epoch, 8 * 60 * 60)
    if len(rows_1h) < 6 or len(rows_8h) < 10:
        return {
            "symbol": symbol,
            "score": None,
            "label": None,
            "reason": "Insufficient data for volatility opportunity scoring.",
            "confidence_label": "LOW",
            "stretch_score": None,
            "volatility_spike_score": None,
            "bounce_context_score": None,
            "liquidity_quality_score": None,
            "observed_history_span_minutes": round(observed_span_minutes, 3),
            "observed_point_count": len(sorted_rows),
            "insufficient_data": True,
            "insufficient_reason_code": "insufficient_window_coverage",
            "insufficient_reason_message": "Not enough 1h/8h coverage for reliable scoring.",
        }

    current_price = latest.price
    one_hour_prices = [row.price for row in rows_1h]
    mean_price = _avg(one_hour_prices)
    if mean_price is None or mean_price <= 0:
        return {
            "symbol": symbol,
            "score": None,
            "label": None,
            "reason": "Insufficient data for volatility opportunity scoring.",
            "confidence_label": "LOW",
            "stretch_score": None,
            "volatility_spike_score": None,
            "bounce_context_score": None,
            "liquidity_quality_score": None,
            "observed_history_span_minutes": round(observed_span_minutes, 3),
            "observed_point_count": len(sorted_rows),
            "insufficient_data": True,
            "insufficient_reason_code": "invalid_price_window",
            "insufficient_reason_message": "Unable to compute valid 1h mean price.",
        }

    min_price_1h = min(one_hour_prices)
    max_price_1h = max(one_hour_prices)
    midpoint = (min_price_1h + max_price_1h) / 2.0
    below_mean_pct = max(((mean_price - current_price) / mean_price) * 100.0, 0.0)
    below_mid_pct = (
        max(((midpoint - current_price) / midpoint) * 100.0, 0.0)
        if midpoint > 0
        else 0.0
    )
    stretch_score = (
        (0.65 * _clamp(below_mean_pct / 4.5, 0.0, 1.0))
        + (0.35 * _clamp(below_mid_pct / 4.5, 0.0, 1.0))
    ) * 100.0

    baseline_rows = rows_8h
    recent_for_returns = rows_30m if len(rows_30m) >= 6 else rows_1h
    recent_returns: list[float] = []
    for idx in range(1, len(recent_for_returns)):
        prev = recent_for_returns[idx - 1].price
        curr = recent_for_returns[idx].price
        if prev <= 0:
            continue
        recent_returns.append(((curr - prev) / prev) * 100.0)
    baseline_returns: list[float] = []
    for idx in range(1, len(baseline_rows)):
        prev = baseline_rows[idx - 1].price
        curr = baseline_rows[idx].price
        if prev <= 0:
            continue
        baseline_returns.append(((curr - prev) / prev) * 100.0)

    recent_tail_size = max(4, int(len(recent_returns) * 0.35))
    recent_tail = recent_returns[-recent_tail_size:] if recent_returns else []
    recent_vol = _stddev(recent_tail)
    baseline_vol = max(_stddev(baseline_returns), 1e-6)
    vol_ratio = recent_vol / baseline_vol
    ratio_norm = _clamp((vol_ratio - 1.0) / 2.2, 0.0, 1.0)

    baseline_prices = [row.price for row in baseline_rows]
    baseline_mean = _avg(baseline_prices) or 0.0
    recent_mean = mean_price
    recent_range_pct = (
        ((max_price_1h - min_price_1h) / recent_mean) * 100.0
        if recent_mean > 0
        else 0.0
    )
    baseline_range_pct = (
        ((max(baseline_prices) - min(baseline_prices)) / baseline_mean) * 100.0
        if baseline_mean > 0
        else 0.0
    )
    range_ratio = (recent_range_pct / baseline_range_pct) if baseline_range_pct > 0 else 0.0
    range_norm = _clamp((range_ratio - 1.0) / 2.0, 0.0, 1.0)
    volatility_spike_score = ((0.6 * ratio_norm) + (0.4 * range_norm)) * 100.0

    range_size = max(max_price_1h - min_price_1h, 1e-9)
    range_pos = (current_price - min_price_1h) / range_size
    near_low_norm = _clamp(1.0 - range_pos, 0.0, 1.0)
    flush_norm = _clamp(((max_price_1h - current_price) / max(max_price_1h, 1e-9)) * 100.0 / 6.0, 0.0, 1.0)
    lookback_size = max(4, int(len(rows_1h) * 0.3))
    lookback_price = rows_1h[max(0, len(rows_1h) - lookback_size)].price
    short_momentum_pct = (
        ((current_price - lookback_price) / lookback_price) * 100.0
        if lookback_price > 0
        else 0.0
    )
    momentum_norm = _clamp((short_momentum_pct + 1.5) / 4.0, 0.0, 1.0)
    bleed_penalty = _clamp(abs(min(short_momentum_pct, 0.0)) / 3.0, 0.0, 1.0)
    vol_assist = _clamp(volatility_spike_score / 100.0, 0.0, 1.0)
    bounce_context_score = _clamp(
        (
            (0.35 * near_low_norm)
            + (0.30 * flush_norm)
            + (0.25 * momentum_norm)
            + (0.10 * vol_assist)
            - (0.25 * bleed_penalty)
        ) * 100.0,
        0.0,
        100.0,
    )

    spread_bps = latest.spread_bps
    quality = str(latest.quality or "").lower()
    liquidity_quality_score: float | None
    if spread_bps <= 0 and not quality:
        liquidity_quality_score = None
    else:
        score = 65.0
        if spread_bps <= 5:
            score = 100.0
        elif spread_bps <= 15:
            score = 90.0
        elif spread_bps <= 30:
            score = 75.0
        elif spread_bps <= 60:
            score = 60.0
        elif spread_bps <= 120:
            score = 40.0
        elif spread_bps <= 250:
            score = 25.0
        else:
            score = 10.0
        if quality and quality != "ok":
            if "spread_too_wide" in quality:
                score -= 25.0
            elif "order_book_tape_mismatch" in quality:
                score -= 20.0
            elif "warming_up_history" in quality:
                score -= 15.0
            else:
                score -= 10.0
        liquidity_quality_score = _clamp(score, 0.0, 100.0)

    components = [
        (stretch_score, 0.35),
        (volatility_spike_score, 0.35),
        (bounce_context_score, 0.20),
    ]
    if liquidity_quality_score is not None:
        components.append((liquidity_quality_score, 0.10))
    total_weight = sum(weight for _, weight in components)
    score = (
        sum((value * weight) for value, weight in components) / total_weight
        if total_weight > 0
        else 0.0
    )
    label = _opportunity_label(score)

    confidence_label = "LOW"
    if len(sorted_rows) >= 80 and observed_span_minutes >= 240.0:
        confidence_label = "HIGH"
    elif len(sorted_rows) >= 30 and observed_span_minutes >= 90.0:
        confidence_label = "MEDIUM"

    reason = _build_opportunity_reason(
        stretch_score,
        volatility_spike_score,
        bounce_context_score,
        liquidity_quality_score,
    )

    return {
        "symbol": symbol,
        "score": round(score, 3),
        "label": label,
        "reason": reason,
        "confidence_label": confidence_label,
        "stretch_score": round(stretch_score, 3),
        "volatility_spike_score": round(volatility_spike_score, 3),
        "bounce_context_score": round(bounce_context_score, 3),
        "liquidity_quality_score": (
            round(liquidity_quality_score, 3)
            if liquidity_quality_score is not None
            else None
        ),
        "observed_history_span_minutes": round(observed_span_minutes, 3),
        "observed_point_count": len(sorted_rows),
        "insufficient_data": False,
        "insufficient_reason_code": None,
        "insufficient_reason_message": None,
    }


def _build_volatility_opportunity_rows(
    symbols: set[str],
    snapshots_by_symbol: dict[str, list[SnapshotPoint]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol in sorted(symbols):
        symbol_rows = snapshots_by_symbol.get(symbol, [])
        rows.append(_build_symbol_volatility_opportunity(symbol, symbol_rows))
    rows.sort(
        key=lambda item: (
            -_to_float(item.get("score"), -1.0),
            str(item.get("symbol") or ""),
        )
    )
    return rows


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
    regime_route_effectiveness = _build_regime_route_effectiveness(
        day_buys=day_buys,
        day_sells=day_sells,
    )
    stale_redeploy_window = _stale_release_redeploy_attribution(
        trades,
        stale_exit_start_ts=day_start,
        stale_exit_end_ts=next_day_start,
    )
    stale_redeploy_total = _stale_release_redeploy_attribution(trades)
    closed_trade_mae_mfe_by_route = _build_closed_trade_mae_mfe_by_route(
        trades=trades,
        day_start_ts=day_start,
        day_end_ts=next_day_start,
        snapshots_by_symbol=snapshots_by_symbol,
        snapshot_ts_cache=snapshot_ts_cache,
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
    slippage_penalty_usd = 0.0
    slippage_samples = 0
    execution_fee_usd = 0.0
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
        fee_usd = _to_float(trade.get("fee_usd"), fallback=0.0)
        if fee_usd > 0:
            execution_fee_usd += fee_usd
        quoted_price = _to_float(trade.get("quoted_price"), fallback=0.0)
        if quoted_price > 0:
            slippage_penalty_usd += abs(price - quoted_price) * size
            slippage_samples += 1
        else:
            slippage_usd = _to_float(trade.get("slippage_usd"), fallback=0.0)
            if slippage_usd > 0:
                slippage_penalty_usd += slippage_usd
                slippage_samples += 1

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
    execution_metrics = aggregate_execution_metrics(day_trades)

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
    rotation_symbols = {
        _normalize_symbol(trade.get("symbol"))
        for trade in trades
        if _normalize_symbol(trade.get("symbol"))
    } | set(snapshot_symbols)
    closed_by_symbol = _build_closed_trades_by_symbol(
        trades,
        stale_review_age_hours_threshold,
        stale_review_unrealized_pnl_pct_threshold,
    )
    symbol_rotation_rows = _build_symbol_rotation_rows(
        rotation_symbols,
        closed_by_symbol,
        generated_at_epoch,
    )
    rotation_status_counts: dict[str, int] = {
        "Rising": 0,
        "Strong": 0,
        "Neutral": 0,
        "Weakening": 0,
        "Cold": 0,
        "Capital Trap Risk": 0,
    }
    for row in symbol_rotation_rows:
        status = str(row.get("status") or "Neutral")
        if status not in rotation_status_counts:
            status = "Neutral"
        rotation_status_counts[status] += 1
    top_rising_symbols = [
        row.get("symbol")
        for row in sorted(
            [r for r in symbol_rotation_rows if str(r.get("status")) in {"Rising", "Strong"}],
            key=lambda item: (
                -_to_float(item.get("rotation_delta"), 0.0),
                -_to_float(item.get("short_term_score"), 0.0),
                str(item.get("symbol") or ""),
            ),
        )[:5]
    ]
    top_cold_symbols = [
        row.get("symbol")
        for row in sorted(
            [r for r in symbol_rotation_rows if str(r.get("status")) in {"Cold", "Capital Trap Risk", "Weakening"}],
            key=lambda item: (
                _to_float(item.get("short_term_score"), 100.0),
                _to_float(item.get("rotation_delta"), 0.0),
                str(item.get("symbol") or ""),
            ),
        )[:5]
    ]
    volatility_opportunity_rows = _build_volatility_opportunity_rows(
        rotation_symbols,
        snapshots_by_symbol,
    )
    valid_volatility_rows = [
        row
        for row in volatility_opportunity_rows
        if not bool(row.get("insufficient_data"))
        and row.get("score") is not None
    ]
    top_volatility_opportunity_symbols = [
        row.get("symbol")
        for row in valid_volatility_rows[:5]
    ]
    highest_opportunity_score = (
        _to_float(valid_volatility_rows[0].get("score"), 0.0)
        if valid_volatility_rows
        else None
    )
    symbols_flagged_high_opportunity_count = sum(
        1
        for row in valid_volatility_rows
        if str(row.get("label") or "") == "HIGH"
    )
    capital_lockup_by_route = _build_capital_lockup_by_route(
        positions=positions,
        snapshots_by_symbol=snapshots_by_symbol,
        generated_at_epoch=generated_at_epoch,
        stale_age_hours_threshold=stale_review_age_hours_threshold,
    )
    top_lockup_route = (
        capital_lockup_by_route["routes"][0]
        if capital_lockup_by_route.get("routes")
        else None
    )
    coverage_end_age_hours = max((generated_at_epoch - next_day_start) / 3600.0, 0.0)
    is_fresh = coverage_end_age_hours <= 30.0
    report = {
        "generated_at": generated_at.isoformat(),
        "generated_at_utc": generated_at.isoformat(),
        "coverage": {
            "window_type": "daily",
            "day_utc": day_iso,
            "start_utc": day_start_dt.isoformat(),
            "end_utc": next_day_start_dt.isoformat(),
            "window_days": 1,
        },
        "freshness": {
            "indicator": "fresh" if is_fresh else "stale",
            "is_fresh": is_fresh,
            "coverage_end_age_hours": round(coverage_end_age_hours, 3),
        },
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
            "rotation_rising_count": rotation_status_counts["Rising"],
            "rotation_strong_count": rotation_status_counts["Strong"],
            "rotation_neutral_count": rotation_status_counts["Neutral"],
            "rotation_weakening_count": rotation_status_counts["Weakening"],
            "rotation_cold_count": rotation_status_counts["Cold"],
            "rotation_capital_trap_risk_count": rotation_status_counts["Capital Trap Risk"],
            "top_volatility_opportunity_symbols": top_volatility_opportunity_symbols,
            "highest_opportunity_score": (
                round(highest_opportunity_score, 3)
                if highest_opportunity_score is not None
                else None
            ),
            "symbols_flagged_high_opportunity_count": symbols_flagged_high_opportunity_count,
            "capital_lockup_overall_weighted_age_hours": capital_lockup_by_route.get(
                "overall_weighted_age_hours"
            ),
            "capital_lockup_top_route": (
                str((top_lockup_route or {}).get("route"))
                if top_lockup_route
                else None
            ),
            "capital_lockup_top_route_weighted_age_hours": (
                (top_lockup_route or {}).get("weighted_age_hours")
                if top_lockup_route
                else None
            ),
            "capital_lockup_top_route_notional_usd": (
                (top_lockup_route or {}).get("total_notional_usd")
                if top_lockup_route
                else None
            ),
            "stale_release_exits_day": int(stale_redeploy_window.get("stale_release_exits") or 0),
            "stale_redeploy_rate_day_pct": stale_redeploy_window.get("redeploy_rate_pct"),
            "stale_redeploy_close_rate_day_pct": stale_redeploy_window.get("close_rate_after_redeploy_pct"),
            "closed_trade_mae_mfe_samples_day": int(
                closed_trade_mae_mfe_by_route.get("sample_count") or 0
            ),
            "regime_route_closed_trades": int(
                regime_route_effectiveness.get("total_closed_trades") or 0
            ),
            "best_regime_route_by_avg_pnl": (
                str(regime_route_effectiveness.get("best_route_by_avg_pnl") or "")
                or None
            ),
            "best_regime_route_avg_pnl_usd": regime_route_effectiveness.get(
                "best_route_avg_pnl_usd"
            ),
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
            },
            "rolling_symbol_rotation": {
                "short_window": {
                    "days": 7,
                    "max_closed_trades": 10,
                },
                "medium_window": {
                    "days": 30,
                    "max_closed_trades": 30,
                },
                "status_counts": rotation_status_counts,
                "top_rising_symbols": top_rising_symbols,
                "top_cold_symbols": top_cold_symbols,
                "symbols": symbol_rotation_rows,
                "note": (
                    "Advisory-only rolling monitor derived from recent closed trade outcomes; does not change strategy or execution."
                ),
            },
            "volatility_opportunity_radar": {
                "top_symbols": top_volatility_opportunity_symbols,
                "highest_score": (
                    round(highest_opportunity_score, 3)
                    if highest_opportunity_score is not None
                    else None
                ),
                "high_opportunity_symbol_count": symbols_flagged_high_opportunity_count,
                "symbols": volatility_opportunity_rows,
                "note": (
                    "Advisory-only near-term volatility opportunity radar derived from observed snapshots; does not change strategy or execution."
                ),
            },
            "regime_route_effectiveness": regime_route_effectiveness,
            "stale_release_redeploy_window": {
                **stale_redeploy_window,
                "note": (
                    "Advisory-only stale-release redeploy attribution for this day window."
                ),
            },
            "stale_release_redeploy_total": {
                **stale_redeploy_total,
                "note": (
                    "Advisory-only stale-release redeploy attribution across full available trade history."
                ),
            },
            "closed_trade_mae_mfe_by_route": closed_trade_mae_mfe_by_route,
            "capital_lockup_by_route": {
                **capital_lockup_by_route,
                "note": (
                    "Advisory-only open-capital lock-up profile by route; "
                    "used for diagnostics and tuning, not direct execution changes."
                ),
            },
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
            "estimated_slippage_penalty_usd": round(slippage_penalty_usd, 4),
            "slippage_sample_count": slippage_samples,
            "execution_fee_usd": round(execution_fee_usd, 4),
            "fill_realism_notes": (
                "Paper fills can apply configurable fees/slippage/partials/timeouts. "
                "If paper_execution.enabled is false, fills remain idealized."
            ),
        },
        "execution_observability": execution_metrics,
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
