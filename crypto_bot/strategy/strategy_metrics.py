from __future__ import annotations

import time

from strategy import strategy_runtime_state as rt
from strategy.route_metadata import record_route_metadata as _record_route_metadata_impl


def record_route_metadata(*, symbol: str, route: dict, parse_numeric):
    changed = _record_route_metadata_impl(
        symbol=symbol,
        route=route,
        route_maps=rt.ROUTE_METADATA_MAPS,
        parse_numeric=parse_numeric,
    )
    if changed:
        rt._metrics_dirty = True


def record_symbol_metrics(
    *,
    symbol,
    regime,
    score,
    volatility,
    parse_numeric,
    record_symbol_metrics_impl,
):
    changed = record_symbol_metrics_impl(
        symbol=symbol,
        regime=regime,
        score=score,
        volatility=volatility,
        last_regime_state=rt._last_regime,
        last_score_state=rt._last_score,
        last_volatility_state=rt._last_volatility,
        parse_numeric=parse_numeric,
        score_epsilon=rt.SCORE_EPSILON,
        volatility_epsilon=rt.VOLATILITY_EPSILON,
    )
    if changed:
        rt._metrics_dirty = True


def record_buy_block_gate(*, symbol, action, reason, normalize_strategy):
    if action == "BUY":
        return
    # Buy-block diagnostics are only for symbols without an open position.
    if symbol in rt._entry_price:
        return

    symbol_key = str(symbol or "").strip().upper()
    if not symbol_key:
        return

    reason_key = str(reason or "").strip().lower()
    if not reason_key:
        reason_key = "unknown"
    route_key = normalize_strategy(
        rt._last_effective_route.get(symbol_key) or rt._last_effective_strategy.get(symbol_key),
        fallback="mean_reversion",
    )

    changed = False
    if rt._last_buy_block_reason.get(symbol_key) != reason_key:
        rt._last_buy_block_reason[symbol_key] = reason_key
        changed = True
    if rt._last_buy_block_route.get(symbol_key) != route_key:
        rt._last_buy_block_route[symbol_key] = route_key
        changed = True

    symbol_bucket = rt._buy_block_counts_by_symbol.get(symbol_key)
    if not isinstance(symbol_bucket, dict):
        symbol_bucket = {}
    symbol_bucket[reason_key] = int(symbol_bucket.get(reason_key, 0) or 0) + 1
    rt._buy_block_counts_by_symbol[symbol_key] = symbol_bucket
    changed = True

    symbol_route_bucket = rt._buy_block_counts_by_symbol_route.get(symbol_key)
    if not isinstance(symbol_route_bucket, dict):
        symbol_route_bucket = {}
    route_bucket = symbol_route_bucket.get(route_key)
    if not isinstance(route_bucket, dict):
        route_bucket = {}
    route_bucket[reason_key] = int(route_bucket.get(reason_key, 0) or 0) + 1
    symbol_route_bucket[route_key] = route_bucket
    rt._buy_block_counts_by_symbol_route[symbol_key] = symbol_route_bucket
    changed = True

    if changed:
        rt._metrics_dirty = True


def flush_metrics_state_if_due(*, save_strategy_state, force=False):
    if not rt._metrics_dirty:
        return

    now = time.time()
    if not force and (now - rt._last_metrics_flush_at) < rt.METRICS_FLUSH_INTERVAL_SECONDS:
        return

    save_strategy_state()
