from __future__ import annotations

import time

from strategy import strategy_runtime_state as rt
from strategy.route_metadata import cleanup_symbol as cleanup_route_metadata_symbol


def _normalize_strategy(value, fallback: str = "mean_reversion") -> str:
    raw = str(value or "").strip().lower()
    if raw in {"mean_reversion", "trend_pullback", "breakout_momentum", "observe_only", "volatility_scalper"}:
        return raw
    return fallback


def _safe_confidence_value(value, *, parse_numeric):
    parsed = parse_numeric(value, fallback=None)
    if parsed is None:
        return None
    if 0 <= parsed <= 1.0:
        parsed *= 100.0
    return max(0.0, min(parsed, 100.0))


def _exit_policy_for_route(route: str) -> str:
    normalized = _normalize_strategy(route, fallback="mean_reversion")
    if normalized == "trend_pullback":
        return rt.EXIT_POLICY_TREND
    if normalized == "breakout_momentum":
        return rt.EXIT_POLICY_BREAKOUT
    if normalized == "volatility_scalper":
        return rt.EXIT_POLICY_SCALPER
    return rt.EXIT_POLICY_MR


def _active_route_for_position(symbol: str, fallback_route: str) -> str:
    stored = _normalize_strategy(rt._entry_route.get(symbol), fallback="")
    if stored:
        return stored
    return _normalize_strategy(fallback_route, fallback="mean_reversion")


def _active_exit_policy_for_position(symbol: str, active_route: str) -> str:
    existing = str(rt._exit_policy.get(symbol) or "").strip().lower()
    if existing in {rt.EXIT_POLICY_MR, rt.EXIT_POLICY_TREND, rt.EXIT_POLICY_BREAKOUT, rt.EXIT_POLICY_SCALPER}:
        return existing
    return _exit_policy_for_route(active_route)


def stage_entry_contract(symbol: str, contract: dict | None):
    if not isinstance(contract, dict):
        rt._pending_entry_contract.pop(symbol, None)
        return
    rt._pending_entry_contract[symbol] = {
        "entry_route": contract.get("entry_route"),
        "entry_regime": contract.get("entry_regime"),
        "exit_policy": contract.get("exit_policy"),
        "entry_confidence": contract.get("entry_confidence"),
        "entry_timestamp": contract.get("entry_timestamp"),
        "route_eval_ts": contract.get("route_eval_ts"),
        "regime_eval_ts": contract.get("regime_eval_ts"),
    }


def clear_entry_contract(symbol: str):
    rt._pending_entry_contract.pop(symbol, None)


def _attach_entry_contract_candidate(
    *,
    decision: dict,
    active_strategy: str,
    route: dict,
    parse_numeric,
) -> dict:
    if not isinstance(decision, dict) or decision.get("action") != "BUY":
        return decision
    now_epoch = time.time()
    decision.setdefault("entry_route", _normalize_strategy(active_strategy, fallback="mean_reversion"))
    decision.setdefault(
        "entry_regime",
        str(route.get("suggested_regime_v2") or route.get("detected_regime") or "MIXED_OR_UNCLEAR"),
    )
    decision.setdefault("exit_policy", _exit_policy_for_route(decision.get("entry_route")))
    decision.setdefault("entry_confidence", _safe_confidence_value(route.get("detected_regime_confidence"), parse_numeric=parse_numeric))
    decision.setdefault("entry_timestamp", now_epoch)
    decision.setdefault("entry_route_eval_ts", parse_numeric(route.get("route_eval_ts"), fallback=now_epoch) or now_epoch)
    decision.setdefault("entry_regime_eval_ts", parse_numeric(route.get("regime_eval_ts"), fallback=now_epoch) or now_epoch)
    return decision


def confirm_entry(
    symbol: str,
    price: float,
    *,
    parse_numeric,
    save_strategy_state,
    entry_route: str | None = None,
    entry_regime: str | None = None,
    exit_policy: str | None = None,
    entry_confidence: float | None = None,
    entry_timestamp: float | None = None,
    route_eval_ts: float | None = None,
    regime_eval_ts: float | None = None,
):
    staged = rt._pending_entry_contract.pop(symbol, None)
    if isinstance(staged, dict):
        if entry_route is None:
            entry_route = staged.get("entry_route")
        if entry_regime is None:
            entry_regime = staged.get("entry_regime")
        if exit_policy is None:
            exit_policy = staged.get("exit_policy")
        if entry_confidence is None:
            entry_confidence = staged.get("entry_confidence")
        if entry_timestamp is None:
            entry_timestamp = staged.get("entry_timestamp")
        if route_eval_ts is None:
            route_eval_ts = staged.get("route_eval_ts")
        if regime_eval_ts is None:
            regime_eval_ts = staged.get("regime_eval_ts")

    now = time.time()
    resolved_route = _normalize_strategy(
        entry_route or rt._last_effective_route.get(symbol) or rt._last_effective_strategy.get(symbol),
        fallback="mean_reversion",
    )
    resolved_exit_policy = str(exit_policy or _exit_policy_for_route(resolved_route)).strip().lower()
    if resolved_exit_policy not in {rt.EXIT_POLICY_MR, rt.EXIT_POLICY_TREND, rt.EXIT_POLICY_BREAKOUT, rt.EXIT_POLICY_SCALPER}:
        resolved_exit_policy = _exit_policy_for_route(resolved_route)
    resolved_timestamp = parse_numeric(entry_timestamp, fallback=now) or now
    resolved_route_eval_ts = parse_numeric(route_eval_ts, fallback=resolved_timestamp) or resolved_timestamp
    resolved_regime_eval_ts = parse_numeric(regime_eval_ts, fallback=resolved_timestamp) or resolved_timestamp
    resolved_confidence = _safe_confidence_value(entry_confidence, parse_numeric=parse_numeric)
    resolved_regime = str(
        entry_regime
        or rt._last_suggested_regime_v2.get(symbol)
        or rt._last_detected_regime.get(symbol)
        or "MIXED_OR_UNCLEAR"
    )

    rt._entry_price[symbol] = price
    rt._entry_time[symbol] = resolved_timestamp
    rt._entry_route[symbol] = resolved_route
    rt._entry_regime[symbol] = resolved_regime
    rt._exit_policy[symbol] = resolved_exit_policy
    rt._entry_confidence[symbol] = resolved_confidence
    rt._entry_timestamp[symbol] = resolved_timestamp
    rt._entry_route_eval_ts[symbol] = resolved_route_eval_ts
    rt._entry_regime_eval_ts[symbol] = resolved_regime_eval_ts
    rt._profit_lock[symbol] = None
    rt._peak_pnl[symbol] = 0.0
    rt._last_signal[symbol] = "BUY"
    save_strategy_state()


def _cleanup(symbol, price, *, route_metadata_maps):
    rt._last_sell_price[symbol] = price
    rt._pending_entry_contract.pop(symbol, None)
    rt._entry_price.pop(symbol, None)
    rt._entry_time.pop(symbol, None)
    rt._entry_route.pop(symbol, None)
    rt._entry_regime.pop(symbol, None)
    rt._exit_policy.pop(symbol, None)
    rt._entry_confidence.pop(symbol, None)
    rt._entry_timestamp.pop(symbol, None)
    rt._entry_route_eval_ts.pop(symbol, None)
    rt._entry_regime_eval_ts.pop(symbol, None)
    rt._profit_lock.pop(symbol, None)
    rt._peak_pnl.pop(symbol, None)
    rt._last_signal.pop(symbol, None)
    rt._last_momentum.pop(symbol, None)
    rt._last_regime.pop(symbol, None)
    rt._last_score.pop(symbol, None)
    rt._last_volatility.pop(symbol, None)
    cleanup_route_metadata_symbol(symbol, route_metadata_maps)


def confirm_exit(symbol: str, price: float, *, route_metadata_maps, save_strategy_state):
    _cleanup(symbol, price, route_metadata_maps=route_metadata_maps)
    save_strategy_state()
