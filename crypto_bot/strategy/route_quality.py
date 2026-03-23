from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from utils.state_io import read_json_file

ROUTE_MEAN_REVERSION = "mean_reversion"
ROUTE_TREND_PULLBACK = "trend_pullback"
ROUTE_BREAKOUT_MOMENTUM = "breakout_momentum"
ROUTE_VOLATILITY_SCALPER = "volatility_scalper"
ROUTE_OBSERVE_ONLY = "observe_only"
ROUTE_UNKNOWN = "unknown"

WINDOWS_SECONDS = {
    "7d": 7 * 24 * 60 * 60,
    "30d": 30 * 24 * 60 * 60,
}

_CACHE_TTL_SECONDS = 30.0
_last_cached_report: dict[str, Any] | None = None
_last_cached_at: float = 0.0
_last_cached_trades_mtime: float | None = None
_last_cached_strategy_mtime: float | None = None
_last_cached_config_mtime: float | None = None


def _safe_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _infer_route_from_reason(reason: str | None) -> str:
    text = str(reason or "").strip().lower()
    if not text:
        return ROUTE_UNKNOWN
    if "volatility_scalper" in text or text.startswith("scalper_"):
        return ROUTE_VOLATILITY_SCALPER
    if "trend_pullback" in text:
        return ROUTE_TREND_PULLBACK
    if "breakout_momentum" in text:
        return ROUTE_BREAKOUT_MOMENTUM
    if "observe_only" in text:
        return ROUTE_OBSERVE_ONLY
    if (
        "mean_reversion" in text
        or "buy_zone" in text
        or "profit_lock" in text
        or "structural_break_exit" in text
        or "waiting_for_first_lock" in text
        or "in_position" in text
    ):
        return ROUTE_MEAN_REVERSION
    return ROUTE_UNKNOWN


def _route_from_trade_row(trade: dict[str, Any]) -> str:
    # Prefer explicit route written at execution time.
    for key in ("effective_route", "entry_route", "route", "effective_strategy", "strategy"):
        value = _normalize_route_name(trade.get(key))
        if value in {
            ROUTE_MEAN_REVERSION,
            ROUTE_TREND_PULLBACK,
            ROUTE_BREAKOUT_MOMENTUM,
            ROUTE_VOLATILITY_SCALPER,
            ROUTE_OBSERVE_ONLY,
        }:
            return value
    return _infer_route_from_reason(str(trade.get("reason", "")))


def _empty_route_row() -> dict[str, Any]:
    return {
        "buy_count": 0,
        "sell_count": 0,
        "realized_pnl_usd": 0.0,
        "win_count": 0,
        "loss_count": 0,
        "expectancy_usd": None,
        "win_rate_pct": None,
    }


def _finalize_route_row(row: dict[str, Any]) -> dict[str, Any]:
    sells = int(row.get("sell_count", 0) or 0)
    pnl = float(row.get("realized_pnl_usd", 0.0) or 0.0)
    wins = int(row.get("win_count", 0) or 0)
    out = dict(row)
    out["realized_pnl_usd"] = round(pnl, 6)
    if sells > 0:
        out["expectancy_usd"] = round(pnl / sells, 6)
        out["win_rate_pct"] = round((wins / sells) * 100.0, 2)
    else:
        out["expectancy_usd"] = None
        out["win_rate_pct"] = None
    return out


def _normalize_route_name(value: Any) -> str:
    token = str(value or "").strip().lower()
    if not token:
        return ROUTE_UNKNOWN
    return token


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _aggregate_window(trades: list[dict[str, Any]], now_epoch: float, window_seconds: float | None) -> dict[str, Any]:
    output: dict[str, dict[str, Any]] = {}
    for trade in trades:
        ts = float(trade.get("time", 0) or 0)
        if ts <= 0:
            continue
        if window_seconds is not None and ts < (now_epoch - window_seconds):
            continue

        route = _route_from_trade_row(trade)
        side = str(trade.get("side", "")).upper()
        row = output.setdefault(route, _empty_route_row())

        if side == "BUY":
            row["buy_count"] += 1
            continue
        if side != "SELL":
            continue

        row["sell_count"] += 1
        pnl = float(trade.get("pnl", 0.0) or 0.0)
        row["realized_pnl_usd"] += pnl
        if pnl > 0:
            row["win_count"] += 1
        elif pnl < 0:
            row["loss_count"] += 1

    finalized: dict[str, Any] = {}
    for route, row in output.items():
        finalized[route] = _finalize_route_row(row)
    return finalized


def _count_by_mode(
    *,
    token_regimes: dict[str, Any],
    route_map: dict[str, Any],
) -> dict[str, Any]:
    mode_counts = {
        "AUTO": 0,
        "MANUAL": 0,
    }
    effective_route_counts = {
        "AUTO": {},
        "MANUAL": {},
    }

    for symbol, route_value in route_map.items():
        symbol_key = str(symbol or "").strip().upper()
        if not symbol_key:
            continue
        configured = str(token_regimes.get(symbol_key, "AUTO")).strip().upper()
        mode = "AUTO" if configured == "AUTO" else "MANUAL"
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        route = _normalize_route_name(route_value)
        bucket = effective_route_counts.setdefault(mode, {})
        bucket[route] = int(bucket.get(route, 0) or 0) + 1

    return {
        "symbol_counts": mode_counts,
        "effective_route_counts": effective_route_counts,
    }


def _build_per_token_route_history(
    *,
    trades: list[dict[str, Any]],
    max_items_per_symbol: int = 20,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trade in trades:
        symbol = str(trade.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        ts = _safe_float(trade.get("time"), default=0.0)
        if ts <= 0:
            continue
        grouped.setdefault(symbol, []).append(
            {
                "time": ts,
                "side": str(trade.get("side", "")).strip().upper(),
                "route": _route_from_trade_row(trade),
                "reason": str(trade.get("reason", "")).strip(),
                "pnl": _safe_float(trade.get("pnl"), default=0.0),
            }
        )

    result: dict[str, Any] = {}
    for symbol, events in grouped.items():
        events.sort(key=lambda row: _safe_float(row.get("time"), default=0.0))
        trimmed = events[-max(1, int(max_items_per_symbol)) :]
        route_counts: dict[str, int] = {}
        for item in trimmed:
            route = _normalize_route_name(item.get("route"))
            route_counts[route] = int(route_counts.get(route, 0) or 0) + 1
        result[symbol] = {
            "count": len(trimmed),
            "route_counts": route_counts,
            "history": trimmed,
        }
    return result


def _count_values(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    out: dict[str, int] = {}
    for value in payload.values():
        key = str(value).strip()
        if not key:
            continue
        out[key] = int(out.get(key, 0) or 0) + 1
    return out


def _summarize_failed_gates(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    out: dict[str, int] = {}
    for value in payload.values():
        if isinstance(value, list):
            for gate in value:
                key = str(gate).strip()
                if not key:
                    continue
                out[key] = int(out.get(key, 0) or 0) + 1
    return out


def _summarize_timestamp_fresh(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    out = {"fresh": 0, "stale_or_missing": 0}
    for value in payload.values():
        if isinstance(value, bool) and value:
            out["fresh"] += 1
        else:
            out["stale_or_missing"] += 1
    return out


def _router_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    strategy_defaults = cfg.get("strategy_defaults", {})
    if not isinstance(strategy_defaults, dict):
        return {}
    router = strategy_defaults.get("router", {})
    if not isinstance(router, dict):
        return {}
    return router


def _gate_thresholds(cfg: dict[str, Any], route: str) -> dict[str, float]:
    router = _router_cfg(cfg)
    if route == ROUTE_TREND_PULLBACK:
        return {
            "min_closed_trades": float(router.get("trend_min_closed_trades", 8)),
            "min_win_rate_pct": float(router.get("trend_min_win_rate_pct", 52)),
            "min_expectancy_usd": float(router.get("trend_min_expectancy_usd", 0.25)),
        }
    if route == ROUTE_BREAKOUT_MOMENTUM:
        return {
            "min_closed_trades": float(router.get("breakout_min_closed_trades", 12)),
            "min_win_rate_pct": float(router.get("breakout_min_win_rate_pct", 55)),
            "min_expectancy_usd": float(router.get("breakout_min_expectancy_usd", 0.5)),
        }
    return {
        "min_closed_trades": 0.0,
        "min_win_rate_pct": 0.0,
        "min_expectancy_usd": 0.0,
    }


def _is_route_promoted(cfg: dict[str, Any], route: str, stats_30d: dict[str, Any]) -> tuple[bool, str]:
    if route in {ROUTE_MEAN_REVERSION, ROUTE_VOLATILITY_SCALPER, ROUTE_OBSERVE_ONLY}:
        return True, "always_allowed"
    if route not in {ROUTE_TREND_PULLBACK, ROUTE_BREAKOUT_MOMENTUM}:
        return False, "unknown_route"

    thresholds = _gate_thresholds(cfg, route)
    sell_count = float(stats_30d.get("sell_count", 0) or 0)
    win_rate_pct = stats_30d.get("win_rate_pct")
    expectancy_usd = stats_30d.get("expectancy_usd")

    if sell_count < thresholds["min_closed_trades"]:
        return False, "insufficient_closed_trades"
    if win_rate_pct is None or float(win_rate_pct) < thresholds["min_win_rate_pct"]:
        return False, "win_rate_below_threshold"
    if expectancy_usd is None or float(expectancy_usd) < thresholds["min_expectancy_usd"]:
        return False, "expectancy_below_threshold"
    return True, "promoted"


def build_route_quality_report(*, state_dir: Path, cfg: dict[str, Any], now_epoch: float | None = None) -> dict[str, Any]:
    now = float(now_epoch if now_epoch is not None else time.time())
    trades_path = state_dir / "trades.json"
    strategy_path = state_dir / "strategy_state.json"
    config_path = state_dir / "config.json"

    trades = read_json_file(trades_path, default=[])
    if not isinstance(trades, list):
        trades = []

    strategy_state = read_json_file(strategy_path, default={})
    if not isinstance(strategy_state, dict):
        strategy_state = {}
    token_regimes = cfg.get("token_regimes", {})
    if not isinstance(token_regimes, dict):
        token_regimes = {}

    windows = {
        "all": _aggregate_window(trades, now, None),
    }
    for label, seconds in WINDOWS_SECONDS.items():
        windows[label] = _aggregate_window(trades, now, float(seconds))

    last_effective_route = strategy_state.get("last_effective_route", {}) or {}
    if not isinstance(last_effective_route, dict):
        last_effective_route = {}

    route_usage_current: dict[str, int] = {}
    for route in last_effective_route.values():
        key = _normalize_route_name(route)
        if not key:
            continue
        route_usage_current[key] = route_usage_current.get(key, 0) + 1

    fallback_counts: dict[str, int] = {}
    for reason in (strategy_state.get("last_fallback_reason", {}) or {}).values():
        value = str(reason or "").strip()
        if not value:
            continue
        fallback_counts[value] = fallback_counts.get(value, 0) + 1

    auto_fallback_counts: dict[str, int] = {}
    for reason in (strategy_state.get("last_auto_fallback_reason", {}) or {}).values():
        value = str(reason or "").strip()
        if not value:
            continue
        auto_fallback_counts[value] = auto_fallback_counts.get(value, 0) + 1

    readiness_counts = _count_values(strategy_state.get("last_route_readiness_state", {}))
    shadow_continuity_counts = _count_values(strategy_state.get("last_shadow_continuity_state", {}))
    failed_gate_counts = _summarize_failed_gates(strategy_state.get("last_failed_gates", {}))
    timestamp_fresh_counts = _summarize_timestamp_fresh(strategy_state.get("last_route_timestamp_fresh", {}))
    non_mr_ready_reason_counts = _count_values(strategy_state.get("last_non_mr_ready_reason", {}))

    stats_30d = windows.get("30d", {})
    promoted_routes: dict[str, bool] = {}
    promotion_reasons: dict[str, str] = {}
    for route in [
        ROUTE_MEAN_REVERSION,
        ROUTE_TREND_PULLBACK,
        ROUTE_BREAKOUT_MOMENTUM,
        ROUTE_VOLATILITY_SCALPER,
        ROUTE_OBSERVE_ONLY,
    ]:
        promoted, reason = _is_route_promoted(cfg, route, stats_30d.get(route, {}))
        promoted_routes[route] = promoted
        promotion_reasons[route] = reason

    manual_vs_auto = _count_by_mode(token_regimes=token_regimes, route_map=last_effective_route)
    per_token_history = _build_per_token_route_history(trades=trades, max_items_per_symbol=20)

    return {
        "generated_at_epoch": now,
        "windows": windows,
        "route_usage_summary": route_usage_current,
        "fallback_reason_summary": fallback_counts,
        "auto_fallback_reason_summary": auto_fallback_counts,
        "route_readiness_summary": readiness_counts,
        "shadow_continuity_summary": shadow_continuity_counts,
        "failed_gate_summary": failed_gate_counts,
        "route_timestamp_fresh_summary": timestamp_fresh_counts,
        "non_mr_ready_reason_summary": non_mr_ready_reason_counts,
        "performance_by_effective_route": windows,
        "manual_vs_auto_comparison": manual_vs_auto,
        "per_token_route_history": per_token_history,
        "current": {
            "effective_route_counts": route_usage_current,
            "fallback_reason_counts": fallback_counts,
            "auto_fallback_reason_counts": auto_fallback_counts,
        },
        "promotion": {
            "promoted_routes": promoted_routes,
            "promotion_reasons": promotion_reasons,
        },
    }


def load_route_quality_report_cached(*, state_dir: Path, cfg: dict[str, Any], now_epoch: float | None = None) -> dict[str, Any]:
    global _last_cached_report
    global _last_cached_at
    global _last_cached_trades_mtime
    global _last_cached_strategy_mtime
    global _last_cached_config_mtime

    now = float(now_epoch if now_epoch is not None else time.time())
    trades_mtime = _safe_mtime(state_dir / "trades.json")
    strategy_mtime = _safe_mtime(state_dir / "strategy_state.json")
    config_mtime = _safe_mtime(state_dir / "config.json")
    cache_fresh = (now - _last_cached_at) <= _CACHE_TTL_SECONDS
    file_unchanged = (
        trades_mtime == _last_cached_trades_mtime
        and strategy_mtime == _last_cached_strategy_mtime
        and config_mtime == _last_cached_config_mtime
    )
    if _last_cached_report is not None and cache_fresh and file_unchanged:
        return _last_cached_report

    report = build_route_quality_report(state_dir=state_dir, cfg=cfg, now_epoch=now)
    _last_cached_report = report
    _last_cached_at = now
    _last_cached_trades_mtime = trades_mtime
    _last_cached_strategy_mtime = strategy_mtime
    _last_cached_config_mtime = config_mtime
    return report
