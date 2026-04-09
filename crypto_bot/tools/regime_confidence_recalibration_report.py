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


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def _default_state_dir() -> Path:
    return resolve_state_dir(Path(__file__).resolve().parents[1] / "state")


def _normalize_regime(value: Any) -> str:
    token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not token:
        return "unknown"

    mapping = {
        "bull": "trend_up",
        "bullish": "trend_up",
        "uptrend": "trend_up",
        "trend_up": "trend_up",
        "bear": "trend_down",
        "bearish": "trend_down",
        "downtrend": "trend_down",
        "trend_down": "trend_down",
        "range": "range",
        "ranging": "range",
        "sideways": "range",
        "breakout_up": "breakout_up",
        "breakout_down": "breakout_down",
        "momentum_up": "momentum_up",
        "momentum_down": "momentum_down",
        "volatile": "volatile",
        "high_vol": "volatile",
        "low_vol": "low_vol",
        "choppy": "choppy",
        "unknown": "unknown",
    }
    return mapping.get(token, "unknown")


def _route_from_row(row: dict[str, Any]) -> str:
    for key in ("effective_route", "entry_route", "route", "effective_strategy", "strategy"):
        token = str(row.get(key) or "").strip().lower()
        if token in {
            "mean_reversion",
            "trend_pullback",
            "breakout_momentum",
            "volatility_scalper",
            "observe_only",
        }:
            return token
    reason = str(row.get("reason") or "").strip().lower()
    if "trend_pullback" in reason:
        return "trend_pullback"
    if "breakout_momentum" in reason:
        return "breakout_momentum"
    if "volatility_scalper" in reason or reason.startswith("scalper_"):
        return "volatility_scalper"
    if "observe_only" in reason:
        return "observe_only"
    return "mean_reversion"


def _regime_from_buy_row(row: dict[str, Any]) -> str:
    for key in ("entry_regime", "suggested_regime_v2", "detected_regime", "configured_regime", "regime"):
        regime = _normalize_regime(row.get(key))
        if regime != "unknown":
            return regime
    return "unknown"


def _build_closed_parts(rows: list[dict[str, Any]], *, start_ts: float, end_ts: float) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda item: _f(item.get("time"), 0.0))
    open_lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    closed_parts: list[dict[str, Any]] = []

    for row in ordered:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        side = str(row.get("side") or "").strip().upper()
        size = _f(row.get("size"), 0.0)
        price = _f(row.get("price"), 0.0)
        ts = _f(row.get("time"), 0.0)
        if size <= 0 or price <= 0 or ts <= 0:
            continue

        if side == "BUY":
            open_lots[symbol].append(
                {
                    "size": size,
                    "price": price,
                    "time": ts,
                    "route": _route_from_row(row),
                    "regime": _regime_from_buy_row(row),
                }
            )
            continue
        if side != "SELL":
            continue

        remaining = size
        lots = open_lots.get(symbol, [])
        while remaining > 1e-12 and lots:
            lot = lots[0]
            lot_size = _f(lot.get("size"), 0.0)
            take = min(remaining, lot_size)
            if take <= 0:
                lots.pop(0)
                continue

            entry_price = _f(lot.get("price"), 0.0)
            entry_ts = _f(lot.get("time"), 0.0)
            pnl_usd = (price - entry_price) * take
            entry_notional = entry_price * take
            pnl_pct = ((pnl_usd / entry_notional) * 100.0) if entry_notional > 0 else 0.0
            hold_hours = ((ts - entry_ts) / 3600.0) if ts > entry_ts > 0 else None

            if start_ts <= ts < end_ts:
                closed_parts.append(
                    {
                        "symbol": symbol,
                        "regime": str(lot.get("regime") or "unknown"),
                        "route": str(lot.get("route") or "mean_reversion"),
                        "qty": take,
                        "entry_notional": entry_notional,
                        "pnl_usd": pnl_usd,
                        "pnl_pct": pnl_pct,
                        "hold_hours": hold_hours,
                    }
                )

            lot["size"] = lot_size - take
            remaining -= take
            if _f(lot.get("size"), 0.0) <= 1e-12:
                lots.pop(0)

    return closed_parts


def _regime_stats(closed_parts: list[dict[str, Any]]) -> dict[str, Any]:
    by_regime: dict[str, dict[str, Any]] = {}
    for part in closed_parts:
        regime = _normalize_regime(part.get("regime"))
        route = str(part.get("route") or "mean_reversion").strip().lower()
        bucket = by_regime.setdefault(
            regime,
            {
                "closed_parts": 0,
                "wins": 0,
                "sum_pnl_usd": 0.0,
                "sum_notional": 0.0,
                "hold_hours_values": [],
                "route_counts": {},
            },
        )
        pnl = _f(part.get("pnl_usd"), 0.0)
        bucket["closed_parts"] += 1
        bucket["sum_pnl_usd"] += pnl
        bucket["sum_notional"] += _f(part.get("entry_notional"), 0.0)
        if pnl > 0:
            bucket["wins"] += 1
        hold_hours = part.get("hold_hours")
        if isinstance(hold_hours, (int, float)):
            bucket["hold_hours_values"].append(float(hold_hours))
        route_counts = bucket["route_counts"]
        route_counts[route] = int(route_counts.get(route, 0) or 0) + 1

    stats: dict[str, Any] = {}
    for regime, row in sorted(by_regime.items(), key=lambda item: item[0]):
        closed = int(row.get("closed_parts", 0))
        if closed <= 0:
            continue
        sum_pnl = _f(row.get("sum_pnl_usd"), 0.0)
        sum_notional = _f(row.get("sum_notional"), 0.0)
        stats[regime] = {
            "closed_parts": closed,
            "win_rate_pct": round(_pct(float(row.get("wins", 0) or 0), max(float(closed), 1.0)), 2),
            "expectancy_usd": round(sum_pnl / max(float(closed), 1.0), 6),
            "net_pnl_usd": round(sum_pnl, 6),
            "return_on_notional_pct": round(_pct(sum_pnl, max(sum_notional, 1e-9)), 4),
            "median_hold_hours": _median([float(v) for v in row.get("hold_hours_values", [])]),
            "route_mix": dict(sorted((row.get("route_counts") or {}).items(), key=lambda item: (-item[1], item[0]))),
        }
    return stats


def _confidence_adjustments(
    *,
    recent_stats: dict[str, Any],
    prior_stats: dict[str, Any],
    min_closed_parts: int,
) -> dict[str, Any]:
    regimes = sorted(set(recent_stats.keys()) | set(prior_stats.keys()))
    suggestions: list[dict[str, Any]] = []
    patch_preview: dict[str, Any] = {}

    for regime in regimes:
        recent = recent_stats.get(regime, {}) if isinstance(recent_stats, dict) else {}
        prior = prior_stats.get(regime, {}) if isinstance(prior_stats, dict) else {}
        recent_closed = int(_f(recent.get("closed_parts"), 0.0))
        prior_closed = int(_f(prior.get("closed_parts"), 0.0))
        recent_expectancy = _f(recent.get("expectancy_usd"), 0.0)
        prior_expectancy = _f(prior.get("expectancy_usd"), 0.0)
        recent_win_rate = _f(recent.get("win_rate_pct"), 0.0)
        delta_expectancy = recent_expectancy - prior_expectancy

        if recent_closed < max(int(min_closed_parts), 1):
            suggestions.append(
                {
                    "regime": regime,
                    "action": "hold",
                    "confidence_delta": 0,
                    "reason": (
                        f"insufficient sample ({recent_closed} < {max(int(min_closed_parts), 1)})"
                    ),
                    "recent_closed_parts": recent_closed,
                    "prior_closed_parts": prior_closed,
                }
            )
            continue

        action = "hold"
        delta = 0
        reason = "outcomes stable"
        if recent_expectancy < -0.5 or recent_win_rate < 35.0:
            action = "tighten"
            delta = 5
            reason = "weak weekly outcomes with elevated downside risk"
        elif recent_expectancy < 0.0 or recent_win_rate < 45.0:
            action = "tighten"
            delta = 3
            reason = "negative/weak expectancy in recent window"
        elif recent_expectancy > 0.8 and recent_win_rate >= 68.0 and delta_expectancy >= 0:
            action = "relax"
            delta = -3
            reason = "strong and improving realized outcomes"
        elif recent_expectancy > 0.4 and recent_win_rate >= 60.0 and delta_expectancy >= 0:
            action = "relax"
            delta = -2
            reason = "consistently positive outcomes"

        suggestions.append(
            {
                "regime": regime,
                "action": action,
                "confidence_delta": delta,
                "reason": reason,
                "recent_closed_parts": recent_closed,
                "prior_closed_parts": prior_closed,
                "recent_expectancy_usd": round(recent_expectancy, 6),
                "recent_win_rate_pct": round(recent_win_rate, 2),
                "delta_expectancy_usd": round(delta_expectancy, 6),
            }
        )
        if delta != 0:
            patch_preview.setdefault("strategy_defaults", {}).setdefault("router", {}).setdefault(
                "regime_confidence_adjustments", {}
            )[regime] = delta

    return {
        "min_closed_parts": max(int(min_closed_parts), 1),
        "suggestions": suggestions,
        "config_patch_preview": patch_preview,
        "note": (
            "Advisory-only confidence recalibration guidance from realized outcomes. "
            "No configuration is mutated automatically."
        ),
    }


def build_report(
    *,
    state_dir: Path,
    window_days: float,
    min_closed_parts: int,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    trades_rows = _load_json(state_dir / "trades.json", [])
    if not isinstance(trades_rows, list):
        trades_rows = []
    now = float(now_epoch if now_epoch is not None else time.time())
    days = max(float(window_days), 1.0)
    window_seconds = days * 24.0 * 3600.0
    recent_start = now - window_seconds
    prior_start = now - (window_seconds * 2.0)

    closed_recent = _build_closed_parts(trades_rows, start_ts=recent_start, end_ts=now)
    closed_prior = _build_closed_parts(trades_rows, start_ts=prior_start, end_ts=recent_start)
    recent_stats = _regime_stats(closed_recent)
    prior_stats = _regime_stats(closed_prior)
    guidance = _confidence_adjustments(
        recent_stats=recent_stats,
        prior_stats=prior_stats,
        min_closed_parts=max(int(min_closed_parts), 1),
    )

    return {
        "generated_at_epoch": now,
        "window_days": days,
        "periods": {
            "recent": {
                "start_ts": recent_start,
                "end_ts": now,
                "closed_parts_total": len(closed_recent),
                "regime_stats": recent_stats,
            },
            "prior": {
                "start_ts": prior_start,
                "end_ts": recent_start,
                "closed_parts_total": len(closed_prior),
                "regime_stats": prior_stats,
            },
        },
        "confidence_recalibration": guidance,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly regime-confidence recalibration report.")
    parser.add_argument("--state-dir", default=str(_default_state_dir()))
    parser.add_argument("--days", type=float, default=7.0)
    parser.add_argument("--min-closed-parts", type=int, default=6)
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    if not state_dir.exists():
        raise FileNotFoundError(f"State directory not found: {state_dir}")

    report = build_report(
        state_dir=state_dir,
        window_days=max(args.days, 1.0),
        min_closed_parts=max(int(args.min_closed_parts), 1),
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
