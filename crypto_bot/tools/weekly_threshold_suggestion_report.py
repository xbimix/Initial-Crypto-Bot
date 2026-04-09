from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.state_paths import resolve_state_dir


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return parsed


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


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


def _route_from_row(row: dict[str, Any], *, fallback_reason: str | None = None) -> str:
    for key in ("effective_route", "entry_route", "route", "effective_strategy", "strategy"):
        raw = str(row.get(key) or "").strip().lower()
        if raw in {
            "mean_reversion",
            "trend_pullback",
            "breakout_momentum",
            "volatility_scalper",
            "observe_only",
        }:
            return raw
    return _route_from_buy_reason(fallback_reason or str(row.get("reason") or ""))


def _closed_parts_between(
    rows: list[dict[str, Any]],
    *,
    start_ts: float,
    end_ts: float,
) -> list[dict[str, Any]]:
    """Return FIFO matched close parts whose close timestamp is inside [start_ts, end_ts)."""
    ordered = sorted(rows, key=lambda item: _f(item.get("time"), 0.0))
    open_lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    closed: list[dict[str, Any]] = []

    for row in ordered:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        side = str(row.get("side") or "").strip().upper()
        qty = _f(row.get("size"), 0.0)
        price = _f(row.get("price"), 0.0)
        ts = _f(row.get("time"), 0.0)
        reason = str(row.get("reason") or "")
        if qty <= 0 or price <= 0 or ts <= 0:
            continue

        if side == "BUY":
            open_lots[symbol].append(
                {
                    "size": qty,
                    "price": price,
                    "time": ts,
                    "route": _route_from_row(row, fallback_reason=reason),
                }
            )
            continue

        if side != "SELL":
            continue

        remaining = qty
        lots = open_lots.get(symbol, [])
        while remaining > 1e-12 and lots:
            lot = lots[0]
            lot_size = _f(lot.get("size"), 0.0)
            take = min(remaining, lot_size)
            if take <= 0:
                lots.pop(0)
                continue

            entry_price = _f(lot.get("price"), 0.0)
            entry_notional = entry_price * take
            pnl_usd = (price - entry_price) * take
            pnl_pct = ((pnl_usd / entry_notional) * 100.0) if entry_notional > 0 else 0.0

            if start_ts <= ts < end_ts:
                closed.append(
                    {
                        "symbol": symbol,
                        "route": str(lot.get("route") or "mean_reversion"),
                        "qty": take,
                        "entry_notional": entry_notional,
                        "pnl_usd": pnl_usd,
                        "pnl_pct": pnl_pct,
                        "sell_reason": reason,
                    }
                )

            lot["size"] = lot_size - take
            remaining -= take
            if _f(lot.get("size"), 0.0) <= 1e-12:
                lots.pop(0)

    return closed


def _route_stats_from_closed_parts(parts: list[dict[str, Any]]) -> dict[str, Any]:
    by_route: dict[str, dict[str, Any]] = {}
    for part in parts:
        route = str(part.get("route") or "mean_reversion")
        bucket = by_route.setdefault(
            route,
            {
                "closed_parts": 0,
                "wins": 0,
                "sum_pnl_usd": 0.0,
                "sum_notional": 0.0,
                "pnl_pct_values": [],
            },
        )
        pnl_usd = _f(part.get("pnl_usd"), 0.0)
        bucket["closed_parts"] += 1
        bucket["sum_pnl_usd"] += pnl_usd
        bucket["sum_notional"] += _f(part.get("entry_notional"), 0.0)
        if pnl_usd > 0:
            bucket["wins"] += 1
        bucket["pnl_pct_values"].append(_f(part.get("pnl_pct"), 0.0))

    out: dict[str, Any] = {}
    for route, row in by_route.items():
        closed_parts = int(_f(row.get("closed_parts"), 0.0))
        wins = int(_f(row.get("wins"), 0.0))
        sum_pnl = _f(row.get("sum_pnl_usd"), 0.0)
        sum_notional = _f(row.get("sum_notional"), 0.0)
        pnl_pct_values = [float(v) for v in row.get("pnl_pct_values", [])]
        out[route] = {
            "closed_parts": closed_parts,
            "win_rate_pct": round(_pct(wins, max(closed_parts, 1)), 2),
            "expectancy_usd": round(sum_pnl / max(closed_parts, 1), 6),
            "return_on_notional_pct": round(_pct(sum_pnl, max(sum_notional, 1e-9)), 4),
            "net_pnl_usd": round(sum_pnl, 6),
            "median_pnl_pct": round(sorted(pnl_pct_values)[len(pnl_pct_values) // 2], 6) if pnl_pct_values else None,
        }
    return dict(sorted(out.items(), key=lambda item: item[0]))


def _router_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    strategy_defaults = cfg.get("strategy_defaults", {})
    if not isinstance(strategy_defaults, dict):
        return {}
    router = strategy_defaults.get("router", {})
    return router if isinstance(router, dict) else {}


def _suggestion(
    *,
    path: str,
    current: Any,
    proposed: Any,
    reason: str,
    impact: str,
) -> dict[str, Any]:
    return {
        "path": path,
        "current": current,
        "proposed": proposed,
        "reason": reason,
        "impact": impact,
    }


def _build_threshold_suggestions(
    *,
    recent: dict[str, Any],
    prior: dict[str, Any],
    cfg: dict[str, Any],
    min_closed_parts: int,
) -> dict[str, Any]:
    router = _router_cfg(cfg)
    suggestions: list[dict[str, Any]] = []
    route_analysis: dict[str, Any] = {}

    route_specs = {
        "mean_reversion": {
            "router_prefix": "mean_reversion",
            "min_score_path": "market_regime.min_score_to_buy",
            "stale_hold_path": "profit_locks.stale_exit_max_hold_seconds",
            "stale_pnl_path": "profit_locks.stale_exit_min_pnl_pct",
            "defaults": {
                "min_score": 60.0,
                "stale_hold_seconds": 21 * 24 * 3600,
                "stale_min_pnl_pct": 0.003,
            },
        },
        "trend_pullback": {
            "router_prefix": "trend",
            "conf_key": "auto_trend_min_confidence",
            "stab_key": "auto_trend_min_stability",
            "pers_key": "auto_trend_min_persistence",
            "expectancy_key": "trend_min_expectancy_usd",
            "share_key": "auto_trend_max_route_share_pct",
            "defaults": {
                "conf": 74.0,
                "stab": 68.0,
                "pers": 68.0,
                "expectancy": 0.25,
                "share": 35.0,
            },
        },
        "breakout_momentum": {
            "router_prefix": "breakout",
            "conf_key": "auto_breakout_min_confidence",
            "stab_key": "auto_breakout_min_stability",
            "pers_key": "auto_breakout_min_persistence",
            "expectancy_key": "breakout_min_expectancy_usd",
            "share_key": "auto_breakout_max_route_share_pct",
            "defaults": {
                "conf": 82.0,
                "stab": 76.0,
                "pers": 76.0,
                "expectancy": 0.5,
                "share": 8.0,
            },
        },
    }

    for route, spec in route_specs.items():
        recent_row = recent.get(route, {}) if isinstance(recent, dict) else {}
        prior_row = prior.get(route, {}) if isinstance(prior, dict) else {}
        recent_closed = int(_f(recent_row.get("closed_parts"), 0.0))
        prior_closed = int(_f(prior_row.get("closed_parts"), 0.0))
        recent_expectancy = _f(recent_row.get("expectancy_usd"), 0.0)
        prior_expectancy = _f(prior_row.get("expectancy_usd"), 0.0)
        delta_expectancy = recent_expectancy - prior_expectancy
        recent_win = _f(recent_row.get("win_rate_pct"), 0.0)
        prior_win = _f(prior_row.get("win_rate_pct"), 0.0)
        delta_win = recent_win - prior_win

        route_analysis[route] = {
            "recent": recent_row,
            "prior": prior_row,
            "delta_expectancy_usd": round(delta_expectancy, 6),
            "delta_win_rate_pct": round(delta_win, 2),
        }

        enough_data = recent_closed >= min_closed_parts
        if route == "mean_reversion":
            enough_data = recent_closed >= max(4, min_closed_parts // 2)
        materially_weaker = delta_expectancy <= -0.15 or delta_win <= -8.0
        negative_now = recent_expectancy < 0.0
        materially_strong = recent_expectancy >= 0.35 and delta_expectancy >= 0.15 and recent_win >= 58.0

        if route == "mean_reversion":
            market_regime = cfg.get("market_regime", {})
            if not isinstance(market_regime, dict):
                market_regime = {}
            profit_locks = cfg.get("profit_locks", {})
            if not isinstance(profit_locks, dict):
                profit_locks = {}
            cur_min_score = _f(market_regime.get("min_score_to_buy"), spec["defaults"]["min_score"])
            cur_stale_hold = _f(
                profit_locks.get("stale_exit_max_hold_seconds"),
                spec["defaults"]["stale_hold_seconds"],
            )
            cur_stale_min_pnl = _f(
                profit_locks.get("stale_exit_min_pnl_pct"),
                spec["defaults"]["stale_min_pnl_pct"],
            )

            if enough_data and (negative_now or materially_weaker):
                score_step = 5.0 if recent_expectancy <= -0.5 else 3.0
                prop_min_score = min(90.0, cur_min_score + score_step)
                prop_stale_hold = max(7 * 24 * 3600, cur_stale_hold * 0.8)
                prop_stale_min_pnl = max(0.002, cur_stale_min_pnl)
                if prop_min_score != cur_min_score:
                    suggestions.append(
                        _suggestion(
                            path=spec["min_score_path"],
                            current=cur_min_score,
                            proposed=round(prop_min_score, 2),
                            reason=f"mean_reversion weekly expectancy weakened (delta={delta_expectancy:.3f})",
                            impact="raises MR entry quality bar in weak tape",
                        )
                    )
                if abs(prop_stale_hold - cur_stale_hold) >= 1:
                    suggestions.append(
                        _suggestion(
                            path=spec["stale_hold_path"],
                            current=cur_stale_hold,
                            proposed=round(prop_stale_hold, 2),
                            reason="mean_reversion underperformance with stale-capital risk",
                            impact="faster stale-capital recycling lowers prolonged low-edge exposure",
                        )
                    )
                if prop_stale_min_pnl != cur_stale_min_pnl:
                    suggestions.append(
                        _suggestion(
                            path=spec["stale_pnl_path"],
                            current=cur_stale_min_pnl,
                            proposed=round(prop_stale_min_pnl, 4),
                            reason="maintain conservative stale release edge",
                            impact="keeps stale-release profit requirement non-negative",
                        )
                    )
            elif recent_closed < max(4, min_closed_parts // 2):
                route_analysis[route]["note"] = (
                    f"Insufficient closed parts in recent week ({recent_closed} < {max(4, min_closed_parts // 2)}); hold thresholds."
                )
            elif materially_strong:
                route_analysis[route]["note"] = (
                    "Mean reversion improved with enough sample size; no loosening suggested to avoid extra risk."
                )
            continue

        cur_conf = _f(router.get(spec["conf_key"]), spec["defaults"]["conf"])
        cur_stab = _f(router.get(spec["stab_key"]), spec["defaults"]["stab"])
        cur_pers = _f(router.get(spec["pers_key"]), spec["defaults"]["pers"])
        cur_exp = _f(router.get(spec["expectancy_key"]), spec["defaults"]["expectancy"])
        cur_share = _f(router.get(spec["share_key"]), spec["defaults"]["share"])

        if enough_data and (negative_now or materially_weaker):
            conf_step = 3.0 if recent_expectancy <= -0.25 else 2.0
            stab_step = 3.0 if recent_expectancy <= -0.25 else 2.0
            pers_step = 3.0 if recent_expectancy <= -0.25 else 2.0
            exp_step = 0.20 if recent_expectancy <= -0.25 else 0.10
            share_step = 4.0 if recent_expectancy <= -0.25 else 2.0

            prop_conf = min(95.0, cur_conf + conf_step)
            prop_stab = min(95.0, cur_stab + stab_step)
            prop_pers = min(95.0, cur_pers + pers_step)
            prop_exp = min(5.0, cur_exp + exp_step)
            share_floor = 10.0 if route == "trend_pullback" else 4.0
            prop_share = max(share_floor, cur_share - share_step)

            if prop_conf != cur_conf:
                suggestions.append(
                    _suggestion(
                        path=f"strategy_defaults.router.{spec['conf_key']}",
                        current=cur_conf,
                        proposed=prop_conf,
                        reason=f"{route} expectancy weakened (delta={delta_expectancy:.3f})",
                        impact="tighter confidence gate lowers weak entries",
                    )
                )
            if prop_stab != cur_stab:
                suggestions.append(
                    _suggestion(
                        path=f"strategy_defaults.router.{spec['stab_key']}",
                        current=cur_stab,
                        proposed=prop_stab,
                        reason=f"{route} stability outcomes softened",
                        impact="requires steadier regime persistence before route activation",
                    )
                )
            if prop_pers != cur_pers:
                suggestions.append(
                    _suggestion(
                        path=f"strategy_defaults.router.{spec['pers_key']}",
                        current=cur_pers,
                        proposed=prop_pers,
                        reason=f"{route} recent window underperformed",
                        impact="reduces churn into low-quality route transitions",
                    )
                )
            if prop_exp != cur_exp:
                suggestions.append(
                    _suggestion(
                        path=f"strategy_defaults.router.{spec['expectancy_key']}",
                        current=cur_exp,
                        proposed=round(prop_exp, 3),
                        reason=f"{route} realized expectancy < target",
                        impact="promotion gate requires stronger route edge",
                    )
                )
            if prop_share != cur_share:
                suggestions.append(
                    _suggestion(
                        path=f"strategy_defaults.router.{spec['share_key']}",
                        current=cur_share,
                        proposed=round(prop_share, 2),
                        reason=f"{route} drawdown containment after weak expectancy",
                        impact="caps concentration into a weakening route",
                    )
                )
            continue

        if enough_data and materially_strong:
            # Keep strict thresholds; do not loosen by default.
            route_analysis[route]["note"] = (
                "Route improved with adequate sample size; no loosening suggested to avoid adding risk."
            )
        elif recent_closed < min_closed_parts:
            route_analysis[route]["note"] = (
                f"Insufficient closed parts in recent week ({recent_closed} < {min_closed_parts}); hold thresholds."
            )

    patch_preview: dict[str, Any] = {}
    for item in suggestions:
        path = str(item.get("path") or "")
        if not path:
            continue
        segments = path.split(".")
        cur: dict[str, Any] = patch_preview
        for seg in segments[:-1]:
            nxt = cur.get(seg)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[seg] = nxt
            cur = nxt
        cur[segments[-1]] = item.get("proposed")

    return {
        "route_analysis": route_analysis,
        "suggestions": suggestions,
        "config_patch_preview": patch_preview,
    }


def _default_state_dir() -> Path:
    return resolve_state_dir(Path(__file__).resolve().parents[1] / "state")


def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly threshold suggestion report for RevBot route tuning.")
    parser.add_argument("--state-dir", default=str(_default_state_dir()))
    parser.add_argument("--window-days", type=float, default=7.0)
    parser.add_argument("--min-closed-parts", type=int, default=6)
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    rows = _load_json(state_dir / "trades.json", [])
    cfg = _load_json(state_dir / "config.json", {})
    if not isinstance(rows, list):
        rows = []
    if not isinstance(cfg, dict):
        cfg = {}

    now = time.time()
    window_seconds = max(args.window_days, 1.0) * 24.0 * 3600.0
    recent_start = now - window_seconds
    prior_start = now - (window_seconds * 2.0)

    closed_recent = _closed_parts_between(rows, start_ts=recent_start, end_ts=now)
    closed_prior = _closed_parts_between(rows, start_ts=prior_start, end_ts=recent_start)
    stats_recent = _route_stats_from_closed_parts(closed_recent)
    stats_prior = _route_stats_from_closed_parts(closed_prior)

    threshold_guidance = _build_threshold_suggestions(
        recent=stats_recent,
        prior=stats_prior,
        cfg=cfg,
        min_closed_parts=max(int(args.min_closed_parts), 1),
    )

    out = {
        "generated_at_epoch": now,
        "window_days": max(args.window_days, 1.0),
        "periods": {
            "recent": {
                "start_ts": recent_start,
                "end_ts": now,
                "closed_parts_total": len(closed_recent),
                "route_stats": stats_recent,
            },
            "prior": {
                "start_ts": prior_start,
                "end_ts": recent_start,
                "closed_parts_total": len(closed_prior),
                "route_stats": stats_prior,
            },
        },
        "threshold_guidance": threshold_guidance,
        "notes": [
            "Suggestions are conservative: tighten when expectancy weakens, avoid automatic loosening.",
            "Apply patch preview manually to config, then re-check after one full weekly window.",
        ],
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
