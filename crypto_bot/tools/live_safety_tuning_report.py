from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from collections import defaultdict
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.state_paths import resolve_state_dir


SNAPSHOT_LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+\s+\|\s+INFO\s+\|\s+SNAPSHOT\s+([A-Z0-9-]+)\s+\|\s+(.+)$"
)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return parsed


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


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _pct(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return (numerator / denominator) * 100.0


def _route_from_buy_reason(reason: str) -> str:
    text = str(reason or "").strip().lower()
    if "trend_pullback" in text:
        return "trend_pullback"
    if "breakout_momentum" in text:
        return "breakout_momentum"
    if "volatility_scalper" in text or text.startswith("scalper_"):
        return "volatility_scalper"
    if "observe_only" in text:
        return "observe_only"
    return "mean_reversion"


def _compute_route_realized(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build realized route expectancy using FIFO lot matching."""
    closed_parts = _build_closed_parts(rows)
    return _compute_route_realized_from_closed_parts(closed_parts)


def _build_closed_parts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build realized close parts using FIFO lot matching."""
    open_lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    closed_parts: list[dict[str, Any]] = []

    for row in sorted(rows, key=lambda item: _f(item.get("time"), 0.0)):
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        side = str(row.get("side") or "").strip().upper()
        qty = _f(row.get("size"), 0.0)
        price = _f(row.get("price"), 0.0)
        ts = _f(row.get("time"), 0.0)
        reason = str(row.get("reason") or "")
        if qty <= 0 or price <= 0:
            continue

        if side == "BUY":
            open_lots[symbol].append(
                {
                    "size": qty,
                    "price": price,
                    "time": ts,
                    "route": _route_from_buy_reason(reason),
                    "buy_reason": reason,
                }
            )
            continue

        if side != "SELL":
            continue

        remaining = qty
        lots = open_lots.get(symbol, [])
        while remaining > 1e-12 and lots:
            lot = lots[0]
            take = min(remaining, _f(lot.get("size"), 0.0))
            if take <= 0:
                lots.pop(0)
                continue

            entry_price = _f(lot.get("price"), 0.0)
            entry_ts = _f(lot.get("time"), 0.0)
            route = str(lot.get("route") or "mean_reversion")
            pnl_usd = (price - entry_price) * take
            entry_notional = entry_price * take
            pnl_pct = ((pnl_usd / entry_notional) * 100.0) if entry_notional > 0 else 0.0
            hold_hours = ((ts - entry_ts) / 3600.0) if ts > 0 and entry_ts > 0 else None

            closed_parts.append(
                {
                    "symbol": symbol,
                    "route": route,
                    "qty": take,
                    "entry_price": entry_price,
                    "exit_price": price,
                    "entry_notional": entry_notional,
                    "pnl_usd": pnl_usd,
                    "pnl_pct": pnl_pct,
                    "hold_hours": hold_hours,
                    "sell_reason": reason,
                }
            )

            lot["size"] = _f(lot.get("size"), 0.0) - take
            remaining -= take
            if _f(lot.get("size"), 0.0) <= 1e-12:
                lots.pop(0)
    return closed_parts


def _compute_route_realized_from_closed_parts(closed_parts: list[dict[str, Any]]) -> dict[str, Any]:
    by_route: dict[str, dict[str, Any]] = {}
    for part in closed_parts:
        route = str(part["route"])
        bucket = by_route.setdefault(
            route,
            {
                "closed_parts": 0,
                "wins": 0,
                "losses": 0,
                "sum_pnl_usd": 0.0,
                "sum_entry_notional": 0.0,
                "pnl_pct_values": [],
                "hold_hours_values": [],
                "stale_release_exits": 0,
            },
        )
        pnl = _f(part.get("pnl_usd"), 0.0)
        bucket["closed_parts"] += 1
        bucket["sum_pnl_usd"] += pnl
        bucket["sum_entry_notional"] += _f(part.get("entry_notional"), 0.0)
        if pnl > 0:
            bucket["wins"] += 1
        elif pnl < 0:
            bucket["losses"] += 1
        bucket["pnl_pct_values"].append(_f(part.get("pnl_pct"), 0.0))
        hold_hours = part.get("hold_hours")
        if isinstance(hold_hours, (int, float)):
            bucket["hold_hours_values"].append(float(hold_hours))
        if str(part.get("sell_reason") or "") == "stale_position_risk_release":
            bucket["stale_release_exits"] += 1

    realized_routes: dict[str, dict[str, Any]] = {}
    for route, bucket in by_route.items():
        wins = float(bucket["wins"])
        losses = float(bucket["losses"])
        parts = float(bucket["closed_parts"])
        sum_entry = _f(bucket["sum_entry_notional"], 0.0)
        realized_routes[route] = {
            "closed_parts": int(parts),
            "win_rate_pct": round(_pct(wins, max(wins + losses, 1.0)), 2),
            "expectancy_usd": round(_f(bucket["sum_pnl_usd"], 0.0) / max(parts, 1.0), 6),
            "net_pnl_usd": round(_f(bucket["sum_pnl_usd"], 0.0), 6),
            "return_on_notional_pct": round(_pct(_f(bucket["sum_pnl_usd"], 0.0), max(sum_entry, 1e-9)), 4),
            "median_pnl_pct": _median([float(v) for v in bucket["pnl_pct_values"]]),
            "median_hold_hours": _median([float(v) for v in bucket["hold_hours_values"]]),
            "stale_release_exits": int(bucket["stale_release_exits"]),
        }

    overall = {
        "closed_parts_total": len(closed_parts),
        "routes": dict(sorted(realized_routes.items(), key=lambda item: item[0])),
    }
    return overall


def _max_drawdown_from_trades(trades_rows: list[dict[str, Any]], *, starting_balance: float) -> dict[str, float | None]:
    balances: list[tuple[float, float]] = []
    for row in sorted(trades_rows, key=lambda item: _f(item.get("time"), 0.0)):
        ts = _f(row.get("time"), 0.0)
        bal = _f(row.get("balance"), 0.0)
        if ts <= 0 or bal <= 0:
            continue
        balances.append((ts, bal))

    if not balances:
        equity = max(starting_balance, 0.0)
        for row in sorted(trades_rows, key=lambda item: _f(item.get("time"), 0.0)):
            side = str(row.get("side") or "").strip().upper()
            if side != "SELL":
                continue
            equity += _f(row.get("pnl"), 0.0)
            ts = _f(row.get("time"), 0.0)
            if ts > 0:
                balances.append((ts, equity))

    if not balances:
        return {
            "max_drawdown_usd": None,
            "max_drawdown_pct": None,
        }

    peak = balances[0][1]
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    for _ts, equity in balances:
        if equity > peak:
            peak = equity
            continue
        dd_usd = max(peak - equity, 0.0)
        dd_pct = (dd_usd / peak * 100.0) if peak > 0 else 0.0
        if dd_usd > max_dd_usd:
            max_dd_usd = dd_usd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    return {
        "max_drawdown_usd": round(max_dd_usd, 6),
        "max_drawdown_pct": round(max_dd_pct, 4),
    }


def _trade_performance_summary(
    closed_parts: list[dict[str, Any]],
    *,
    trades_rows: list[dict[str, Any]],
    starting_balance: float,
) -> dict[str, Any]:
    if not closed_parts:
        drawdown = _max_drawdown_from_trades(trades_rows, starting_balance=starting_balance)
        return {
            "closed_parts": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "net_pnl_usd": 0.0,
            "gross_profit_usd": 0.0,
            "gross_loss_usd": 0.0,
            "profit_factor": None,
            "expectancy_per_trade_usd": 0.0,
            "average_hold_hours": None,
            **drawdown,
        }

    wins = 0
    losses = 0
    gross_profit = 0.0
    gross_loss = 0.0
    holds: list[float] = []
    for part in closed_parts:
        pnl = _f(part.get("pnl_usd"), 0.0)
        if pnl > 0:
            wins += 1
            gross_profit += pnl
        elif pnl < 0:
            losses += 1
            gross_loss += pnl
        hold_hours = part.get("hold_hours")
        if isinstance(hold_hours, (int, float)):
            holds.append(float(hold_hours))

    closed = len(closed_parts)
    net = gross_profit + gross_loss
    drawdown = _max_drawdown_from_trades(trades_rows, starting_balance=starting_balance)
    return {
        "closed_parts": closed,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(_pct(float(wins), max(float(closed), 1.0)), 2),
        "net_pnl_usd": round(net, 6),
        "gross_profit_usd": round(gross_profit, 6),
        "gross_loss_usd": round(gross_loss, 6),
        "profit_factor": round(gross_profit / abs(gross_loss), 6) if gross_loss < 0 else None,
        "expectancy_per_trade_usd": round(net / max(float(closed), 1.0), 6),
        "average_hold_hours": round(sum(holds) / len(holds), 6) if holds else None,
        **drawdown,
    }


def _slippage_fee_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    slippages = []
    fees = []
    fill_ratios = []
    for row in rows:
        s = _f(row.get("slippage_bps"), float("nan"))
        if s == s:  # nan-safe check
            slippages.append(float(s))
        fee = _f(row.get("fee_usd"), float("nan"))
        if fee == fee:
            fees.append(float(fee))
        fr = _f(row.get("fill_ratio"), float("nan"))
        if fr == fr:
            fill_ratios.append(float(fr))
    return {
        "slippage_samples": len(slippages),
        "avg_slippage_bps": round(sum(slippages) / len(slippages), 6) if slippages else None,
        "median_slippage_bps": _median(slippages),
        "avg_fee_usd": round(sum(fees) / len(fees), 6) if fees else None,
        "avg_fill_ratio": round(sum(fill_ratios) / len(fill_ratios), 6) if fill_ratios else None,
    }


def _buy_rejection_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buy_rows = [r for r in rows if str(r.get("action", "")).upper() == "BUY"]
    executed = [r for r in buy_rows if bool(r.get("executed", False))]
    blocked = [r for r in buy_rows if not bool(r.get("executed", False))]
    blocked_reasons: dict[str, int] = {}
    for row in blocked:
        reason = str(row.get("blocked_reason") or row.get("decision_reason") or "unknown")
        blocked_reasons[reason] = blocked_reasons.get(reason, 0) + 1
    return {
        "buy_attempts": len(buy_rows),
        "buy_executed": len(executed),
        "buy_blocked": len(blocked),
        "rejection_rate_pct": round(_pct(float(len(blocked)), max(float(len(buy_rows)), 1.0)), 4)
        if buy_rows
        else 0.0,
        "blocked_reason_counts": dict(sorted(blocked_reasons.items(), key=lambda item: (-item[1], item[0]))),
    }


def _parse_snapshot_fields(raw_fields: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for token in raw_fields.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        values[key.strip()] = value.strip().strip(",")
    return values


def _latest_prices_from_log(log_path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    if not log_path.exists():
        return out
    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in reversed(lines):
        match = SNAPSHOT_LINE_RE.match(line)
        if not match:
            continue
        symbol = str(match.group(1) or "").strip().upper()
        if not symbol or symbol in out:
            continue
        fields = _parse_snapshot_fields(match.group(2))
        price = _f(fields.get("price"), 0.0)
        if price > 0:
            out[symbol] = price
    return out


def _stale_open_positions(
    state_dir: Path,
    *,
    stale_max_hold_seconds: float,
    stale_min_pnl_pct: float,
) -> dict[str, Any]:
    paper = _load_json(state_dir / "paper_state.json", {})
    positions = paper.get("positions", {}) if isinstance(paper, dict) else {}
    if not isinstance(positions, dict):
        positions = {}
    prices = _latest_prices_from_log(state_dir / "bot.log")
    now = time.time()
    candidates: list[dict[str, Any]] = []
    stale_total = 0
    all_holds: list[float] = []
    for symbol, row in positions.items():
        if not isinstance(row, dict):
            continue
        entry = _f(row.get("price"), 0.0)
        entry_ts = _f(row.get("entry_time"), 0.0)
        last = _f(prices.get(symbol), 0.0)
        if entry <= 0 or entry_ts <= 0 or last <= 0:
            continue
        hold_seconds = max(0.0, now - entry_ts)
        all_holds.append(hold_seconds / 3600.0)
        if hold_seconds < stale_max_hold_seconds:
            continue
        stale_total += 1
        pnl_pct = ((last - entry) / entry) * 100.0
        if pnl_pct <= (stale_min_pnl_pct * 100.0):
            candidates.append(
                {
                    "symbol": symbol,
                    "hold_hours": round(hold_seconds / 3600.0, 2),
                    "entry_price": entry,
                    "last_price": last,
                    "pnl_pct": round(pnl_pct, 4),
                }
            )

    candidates.sort(key=lambda row: row["hold_hours"], reverse=True)
    return {
        "open_positions": len(positions),
        "stale_positions_total": stale_total,
        "stale_release_candidates": len(candidates),
        "median_open_hold_hours": _median(all_holds),
        "max_open_hold_hours": round(max(all_holds), 4) if all_holds else None,
        "candidates": candidates[:25],
    }


def _stale_release_redeploy_attribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda item: _f(item.get("time"), 0.0))
    stale_indices = [
        idx
        for idx, row in enumerate(ordered)
        if str(row.get("side") or "").strip().upper() == "SELL"
        and str(row.get("reason") or "").strip() == "stale_position_risk_release"
    ]
    if not stale_indices:
        return {
            "stale_release_exits": 0,
            "redeployed": 0,
            "redeploy_rate_pct": 0.0,
            "closed_after_redeploy": 0,
            "close_rate_after_redeploy_pct": 0.0,
            "win_rate_after_redeploy_pct": 0.0,
            "route_stats": {},
            "latest_events": [],
        }

    route_stats: dict[str, dict[str, Any]] = {}
    redeployed = 0
    closed_after_redeploy = 0
    wins = 0
    redeploy_delay_minutes: list[float] = []
    close_delay_hours: list[float] = []
    pnl_pct_values: list[float] = []
    events: list[dict[str, Any]] = []

    for idx in stale_indices:
        stale_row = ordered[idx]
        symbol = str(stale_row.get("symbol") or "").strip().upper()
        stale_ts = _f(stale_row.get("time"), 0.0)
        stale_price = _f(stale_row.get("price"), 0.0)
        stale_size = _f(stale_row.get("size"), 0.0)
        if not symbol:
            continue

        buy_idx: int | None = None
        next_buy: dict[str, Any] | None = None
        for j in range(idx + 1, len(ordered)):
            row = ordered[j]
            if str(row.get("symbol") or "").strip().upper() != symbol:
                continue
            if str(row.get("side") or "").strip().upper() == "BUY":
                next_buy = row
                buy_idx = j
                break

        event: dict[str, Any] = {
            "symbol": symbol,
            "stale_exit_ts": stale_ts,
            "stale_exit_price": stale_price,
            "stale_exit_size": stale_size,
            "redeployed": False,
            "closed_after_redeploy": False,
        }
        if next_buy is None or buy_idx is None:
            events.append(event)
            continue

        buy_ts = _f(next_buy.get("time"), 0.0)
        buy_price = _f(next_buy.get("price"), 0.0)
        buy_size = _f(next_buy.get("size"), 0.0)
        route = _route_from_buy_reason(str(next_buy.get("reason") or ""))
        redeployed += 1
        event["redeployed"] = True
        event["redeploy_ts"] = buy_ts
        event["redeploy_price"] = buy_price
        event["redeploy_size"] = buy_size
        event["redeploy_route"] = route
        if stale_ts > 0 and buy_ts > stale_ts:
            delay_min = (buy_ts - stale_ts) / 60.0
            event["redeploy_delay_minutes"] = round(delay_min, 2)
            redeploy_delay_minutes.append(delay_min)

        route_bucket = route_stats.setdefault(
            route,
            {
                "stale_release_exits": 0,
                "redeployed": 0,
                "closed_after_redeploy": 0,
                "wins": 0,
                "redeploy_delay_minutes_values": [],
                "close_delay_hours_values": [],
                "pnl_pct_values": [],
            },
        )
        route_bucket["stale_release_exits"] += 1
        route_bucket["redeployed"] += 1
        if "redeploy_delay_minutes" in event:
            route_bucket["redeploy_delay_minutes_values"].append(float(event["redeploy_delay_minutes"]))

        close_row: dict[str, Any] | None = None
        for k in range(buy_idx + 1, len(ordered)):
            row = ordered[k]
            if str(row.get("symbol") or "").strip().upper() != symbol:
                continue
            if str(row.get("side") or "").strip().upper() == "SELL":
                close_row = row
                break

        if close_row is None:
            events.append(event)
            continue

        close_ts = _f(close_row.get("time"), 0.0)
        close_price = _f(close_row.get("price"), 0.0)
        close_reason = str(close_row.get("reason") or "")
        close_delay_h = ((close_ts - buy_ts) / 3600.0) if close_ts > buy_ts > 0 else 0.0
        pnl_pct = ((close_price - buy_price) / buy_price) * 100.0 if buy_price > 0 else 0.0

        event["closed_after_redeploy"] = True
        event["close_ts"] = close_ts
        event["close_price"] = close_price
        event["close_reason"] = close_reason
        event["close_delay_hours"] = round(close_delay_h, 3)
        event["redeploy_pnl_pct"] = round(pnl_pct, 4)
        if pnl_pct > 0:
            event["redeploy_outcome"] = "win"
        elif pnl_pct < 0:
            event["redeploy_outcome"] = "loss"
        else:
            event["redeploy_outcome"] = "flat"

        closed_after_redeploy += 1
        route_bucket["closed_after_redeploy"] += 1
        close_delay_hours.append(close_delay_h)
        pnl_pct_values.append(pnl_pct)
        route_bucket["close_delay_hours_values"].append(close_delay_h)
        route_bucket["pnl_pct_values"].append(pnl_pct)
        if pnl_pct > 0:
            wins += 1
            route_bucket["wins"] += 1
        events.append(event)

    stale_release_exits = len(stale_indices)
    route_summary: dict[str, Any] = {}
    for route, row in route_stats.items():
        redeploy_count = int(_f(row.get("redeployed"), 0.0))
        closed_count = int(_f(row.get("closed_after_redeploy"), 0.0))
        route_wins = int(_f(row.get("wins"), 0.0))
        route_summary[route] = {
            "stale_release_exits": int(_f(row.get("stale_release_exits"), 0.0)),
            "redeployed": redeploy_count,
            "closed_after_redeploy": closed_count,
            "redeploy_rate_pct": round(_pct(redeploy_count, max(int(_f(row.get("stale_release_exits"), 0.0)), 1)), 2),
            "close_rate_after_redeploy_pct": round(_pct(closed_count, max(redeploy_count, 1)), 2),
            "win_rate_after_redeploy_pct": round(_pct(route_wins, max(closed_count, 1)), 2),
            "median_redeploy_delay_minutes": _median([float(v) for v in row.get("redeploy_delay_minutes_values", [])]),
            "median_close_delay_hours": _median([float(v) for v in row.get("close_delay_hours_values", [])]),
            "median_redeploy_pnl_pct": _median([float(v) for v in row.get("pnl_pct_values", [])]),
        }

    events.sort(key=lambda item: _f(item.get("stale_exit_ts"), 0.0), reverse=True)
    return {
        "stale_release_exits": stale_release_exits,
        "redeployed": redeployed,
        "redeploy_rate_pct": round(_pct(redeployed, max(stale_release_exits, 1)), 2),
        "closed_after_redeploy": closed_after_redeploy,
        "close_rate_after_redeploy_pct": round(_pct(closed_after_redeploy, max(redeployed, 1)), 2),
        "win_rate_after_redeploy_pct": round(_pct(wins, max(closed_after_redeploy, 1)), 2),
        "median_redeploy_delay_minutes": _median(redeploy_delay_minutes),
        "median_close_delay_hours": _median(close_delay_hours),
        "median_redeploy_pnl_pct": _median(pnl_pct_values),
        "route_stats": dict(sorted(route_summary.items(), key=lambda item: item[0])),
        "latest_events": events[:25],
    }


def _recommendations(report: dict[str, Any]) -> list[str]:
    recs: list[str] = []
    sync = report.get("sync", {})
    audit = report.get("audit", {})
    realized = report.get("realized_window", {})
    stale = report.get("stale_positions", {})
    stale_redeploy_window = report.get("stale_redeploy_window", {})
    stale_redeploy_total = report.get("stale_redeploy_total", {})

    rl_per_h = _f(sync.get("rate_limited_events_per_hour_proxy"))
    degraded_per_h = _f(sync.get("degraded_jobs_per_hour"))
    non_mr_block_rate = _f(audit.get("non_mr_block_rate_pct"))
    blocked_reason_counts = audit.get("blocked_reason_counts", {}) or {}

    if rl_per_h > 8:
        recs.append("High throttle pressure: reduce max_sync_requests_per_tick or increase loop_sleep by 2-3s.")
    elif rl_per_h < 2:
        recs.append("Throttle pressure low: safe to trial +1 sync request cap during active windows.")

    if degraded_per_h > 2:
        recs.append("Degraded sync elevated: prioritize symbol health demotion or widen unsupported backoff.")

    if non_mr_block_rate > 95 and _f(audit.get("non_mr_buy_rows")) >= 20:
        recs.append("Non-MR guard very strict: trial -3 confidence points for a short controlled window.")
    elif non_mr_block_rate < 20 and _f(audit.get("non_mr_buy_rows")) >= 20:
        recs.append("Non-MR routing permissive: tighten non-MR stability/persistence by +5.")

    if isinstance(blocked_reason_counts, dict):
        if blocked_reason_counts.get("route_quality_throttle_pressure", 0) > 0:
            recs.append("Frequent throttle-pressure route blocks: reduce sync request cap baseline by 1.")
        if blocked_reason_counts.get("route_quality_low_confidence", 0) > 0:
            recs.append("Low-confidence dominates blocks: keep confidence gate and improve readiness first.")

    stale_candidates = int(_f(stale.get("stale_release_candidates"), 0))
    if stale_candidates > 0:
        recs.append(
            f"{stale_candidates} stale low-edge open positions detected: monitor `stale_position_risk_release` exits after restart."
        )

    stale_release_exits = int(_f(stale_redeploy_total.get("stale_release_exits"), 0))
    if stale_release_exits > 0:
        redeploy_rate = _f(stale_redeploy_total.get("redeploy_rate_pct"))
        close_rate = _f(stale_redeploy_total.get("close_rate_after_redeploy_pct"))
        win_rate = _f(stale_redeploy_total.get("win_rate_after_redeploy_pct"))
        if redeploy_rate < 30:
            recs.append("Stale-release redeploy rate is low; check symbol readiness freshness and route gate strictness.")
        if close_rate >= 60 and win_rate < 45:
            recs.append("Redeployed trades are closing frequently with weak win-rate; tighten non-MR confidence by +2 to +4.")
        if close_rate >= 60 and win_rate >= 55:
            recs.append("Redeploy outcome quality is acceptable; keep stale-release settings unchanged for now.")
    elif int(_f(stale_redeploy_window.get("stale_release_exits"), 0)) == 0:
        recs.append("No stale-release exits observed in this window; keep collecting data before threshold changes.")

    routes = realized.get("routes", {}) if isinstance(realized, dict) else {}
    for route, row in routes.items():
        expectancy = _f((row or {}).get("expectancy_usd"), 0.0)
        closed = int(_f((row or {}).get("closed_parts"), 0))
        if closed >= 10 and expectancy < 0:
            recs.append(f"Route {route} has negative expectancy in window; tighten its entry filters.")

    if not recs:
        recs.append("No major pressure signals. Keep current thresholds and re-evaluate after another 12h window.")
    return recs


def _default_state_dir() -> Path:
    return resolve_state_dir(Path(__file__).resolve().parents[1] / "state")


def main() -> int:
    parser = argparse.ArgumentParser(description="RevBot live safety tuning report.")
    parser.add_argument("--state-dir", default=str(_default_state_dir()))
    parser.add_argument("--hours", type=float, default=12.0)
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    sync_rows = _load_jsonl(state_dir / "market_sync_health_history.jsonl")
    audit_rows = _load_jsonl(state_dir / "decision_audit.jsonl")
    trades_rows = _load_json(state_dir / "trades.json", [])
    config = _load_json(state_dir / "config.json", {})
    if not isinstance(trades_rows, list):
        trades_rows = []
    if not isinstance(config, dict):
        config = {}
    starting_balance = _f(config.get("starting_balance"), 10000.0) or 10000.0

    now = time.time()
    window_hours = max(args.hours, 0.5)
    cutoff = now - (window_hours * 3600.0)
    sync_rows = [r for r in sync_rows if _f(r.get("ts_epoch"), 0) >= cutoff]
    audit_rows = [r for r in audit_rows if _f(r.get("ts_epoch"), 0) >= cutoff]
    trades_window = [r for r in trades_rows if _f(r.get("time"), 0) >= cutoff]

    report: dict[str, Any] = {
        "window_hours": window_hours,
        "sync_samples": len(sync_rows),
        "audit_samples": len(audit_rows),
        "trade_rows_window": len(trades_window),
        "trade_rows_total": len(trades_rows),
    }

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

    buy_rows = [r for r in audit_rows if str(r.get("action", "")).upper() == "BUY"]
    non_mr = [
        r for r in buy_rows
        if str(r.get("effective_route") or "").upper() not in {"", "MEAN_REVERSION", "MEAN_REVERSION_FRIENDLY"}
    ]
    blocked = [r for r in non_mr if not bool(r.get("executed", False))]
    executed = [r for r in non_mr if bool(r.get("executed", False))]
    blocked_reasons: dict[str, int] = {}
    for row in blocked:
        reason = str(row.get("blocked_reason") or row.get("decision_reason") or "unknown")
        blocked_reasons[reason] = blocked_reasons.get(reason, 0) + 1
    conf_blocked = [_f(r.get("confidence_score")) for r in blocked if r.get("confidence_score") is not None]
    conf_exec = [_f(r.get("confidence_score")) for r in executed if r.get("confidence_score") is not None]
    report["audit"] = {
        "buy_rows": len(buy_rows),
        "non_mr_buy_rows": len(non_mr),
        "non_mr_executed": len(executed),
        "non_mr_blocked": len(blocked),
        "non_mr_block_rate_pct": round(_pct(len(blocked), max(len(non_mr), 1)), 2) if non_mr else 0.0,
        "blocked_reason_counts": dict(sorted(blocked_reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
        "confidence_median_blocked": _median(conf_blocked),
        "confidence_median_executed": _median(conf_exec),
    }

    report["realized_window"] = _compute_route_realized(trades_window)
    report["realized_total"] = _compute_route_realized(trades_rows)
    closed_parts_window = _build_closed_parts(trades_window)
    closed_parts_total = _build_closed_parts(trades_rows)
    report["performance_window"] = _trade_performance_summary(
        closed_parts_window,
        trades_rows=trades_window,
        starting_balance=starting_balance,
    )
    report["performance_total"] = _trade_performance_summary(
        closed_parts_total,
        trades_rows=trades_rows,
        starting_balance=starting_balance,
    )
    report["execution_costs_window"] = _slippage_fee_metrics(trades_window)
    report["execution_costs_total"] = _slippage_fee_metrics(trades_rows)
    report["buy_rejections_window"] = _buy_rejection_summary(audit_rows)
    report["stale_redeploy_window"] = _stale_release_redeploy_attribution(trades_window)
    report["stale_redeploy_total"] = _stale_release_redeploy_attribution(trades_rows)

    stale_cfg = config.get("profit_locks", {}) if isinstance(config.get("profit_locks"), dict) else {}
    stale_max_hold_seconds = _f(stale_cfg.get("stale_exit_max_hold_seconds"), 21 * 24 * 3600)
    stale_min_pnl_pct = _f(stale_cfg.get("stale_exit_min_pnl_pct"), 0.003)
    report["stale_positions"] = _stale_open_positions(
        state_dir,
        stale_max_hold_seconds=stale_max_hold_seconds,
        stale_min_pnl_pct=stale_min_pnl_pct,
    )
    report["stale_settings"] = {
        "stale_exit_max_hold_seconds": stale_max_hold_seconds,
        "stale_exit_min_pnl_pct": stale_min_pnl_pct,
    }

    report["recommendations"] = _recommendations(report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
