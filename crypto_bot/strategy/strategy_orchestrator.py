from __future__ import annotations

import time

from strategy.decision_payloads import build_decision_payload
from strategy.diagnostics import (
    compute_buy_diagnostics as _compute_buy_diagnostics_impl,
    compute_scalper_diagnostics as _compute_scalper_diagnostics_impl,
    record_symbol_metrics as _record_symbol_metrics_impl,
)
from strategy.exits.breakout_exit import evaluate_breakout_exit
from strategy.exits.mr_exit import evaluate_mr_exit
from strategy.exits.trend_exit import evaluate_trend_exit
from strategy.routes.breakout_momentum import evaluate_breakout_momentum_route_entry
from strategy.routes.mean_reversion import evaluate_mean_reversion_entry
from strategy.routes.trend_pullback import evaluate_trend_pullback_route_entry
from strategy.routing import (
    advisory_has_required_fields as _advisory_has_required_fields_impl,
    configured_regime_for_symbol as _configured_regime_for_symbol_impl,
    resolve_scalper_config as _resolve_scalper_config_impl,
    router_cfg as _router_cfg_impl,
    router_flag as _router_flag_impl,
    strategy_for_symbol as _strategy_for_symbol_impl,
)
from strategy.sell_eval import (
    evaluate_scalper_sell as _evaluate_scalper_sell_impl,
    evaluate_sell as _evaluate_sell_impl,
)
from utils.token_regimes import TOKEN_REGIME_AUTO

from strategy import entry_contracts
from strategy import shadow_regime_manager
from strategy import strategy_metrics
from strategy import strategy_runtime_state as rt


def _sync_with_broker_state(ctx):
    ctx._sync_with_broker_state_impl(
        paper_state_file=ctx.PAPER_STATE_FILE,
        read_json_file=ctx.read_json_file,
        parse_numeric=ctx._parse_numeric,
        entry_price=rt._entry_price,
        entry_time=rt._entry_time,
        profit_lock=rt._profit_lock,
        peak_pnl=rt._peak_pnl,
        last_momentum=rt._last_momentum,
        last_signal=rt._last_signal,
        metadata_maps=(
            rt._last_regime,
            rt._last_score,
            rt._last_volatility,
            *rt.ROUTE_METADATA_MAPS.values(),
        ),
        entry_route_state=rt._entry_route,
        entry_regime_state=rt._entry_regime,
        exit_policy_state=rt._exit_policy,
        entry_confidence_state=rt._entry_confidence,
        entry_timestamp_state=rt._entry_timestamp,
        entry_route_eval_ts_state=rt._entry_route_eval_ts,
        entry_regime_eval_ts_state=rt._entry_regime_eval_ts,
        save_strategy_state=ctx._save_strategy_state,
        logger=ctx.logger,
    )


def _paper_state_mtime(ctx):
    return ctx._paper_state_mtime_impl(ctx.PAPER_STATE_FILE)


def _sync_with_broker_state_if_needed(ctx, force: bool = False):
    current_mtime = _paper_state_mtime(ctx)
    if (
        not force
        and rt._synced
        and current_mtime is not None
        and rt._last_paper_state_mtime is not None
        and current_mtime == rt._last_paper_state_mtime
    ):
        return

    _sync_with_broker_state(ctx)
    rt._synced = True
    rt._last_paper_state_mtime = current_mtime


def evaluate_symbol(snapshot: dict, cfg: dict, *, ctx) -> dict:
    _sync_with_broker_state_if_needed(ctx)
    return generate_decision(snapshot, cfg, ctx=ctx)


def generate_decision(snapshot: dict, cfg: dict, *, ctx) -> dict:
    symbol = snapshot["symbol"]
    price = snapshot["price"]

    momentum = snapshot["momentum_norm"]
    trades = snapshot["trade_count"]

    high_24h = snapshot["high_24h"]
    low_24h = snapshot["low_24h"]

    atr = snapshot["atr"]
    vwap = snapshot.get("vwap")
    z_score = None
    if vwap is not None and atr is not None and atr > 0:
        z_score = (price - vwap) / atr

    entry = rt._entry_price.get(symbol)
    prev_mom = rt._last_momentum.get(symbol)
    entry_ts = rt._entry_time.get(symbol)

    min_trades = cfg.get("min_trades", 3)
    regime_cfg = cfg.get("market_regime", {})
    volatility_cfg = cfg.get("volatility_filters", {})
    profit_cfg = cfg.get("profit_locks", {})
    scalper_cfg = ctx._resolve_scalper_config(cfg)
    strategy_mode = ctx._strategy_for_symbol(cfg, symbol, scalper_cfg=scalper_cfg)
    configured_regime = ctx._configured_regime_for_symbol(cfg, symbol)
    route_snapshot = dict(snapshot)
    route_eval_ts = time.time()
    route_snapshot["router_eval_ts"] = route_eval_ts
    shadow_updated_pre_route = False
    pre_route_candidate_regime = None

    if configured_regime == TOKEN_REGIME_AUTO:
        existing_advisory = route_snapshot.get("regime_advisory")
        existing_advisory_valid = ctx._advisory_has_required_fields(existing_advisory)

        if existing_advisory_valid:
            route_snapshot["regime_eval_ts"] = (
                ctx._parse_numeric(existing_advisory.get("analysisAnchorEpoch"), fallback=None)
                or ctx._parse_numeric(existing_advisory.get("analysis_anchor_epoch"), fallback=None)
                or ctx._parse_numeric(existing_advisory.get("detectionTimestampEpoch"), fallback=None)
                or ctx._parse_numeric(existing_advisory.get("detection_timestamp_epoch"), fallback=None)
                or route_eval_ts
            )
        else:
            runtime_advisory_v2 = ctx.evaluate_regime_unified(
                snapshot=route_snapshot,
                now_epoch=route_eval_ts,
                cfg=cfg,
            )
            if isinstance(runtime_advisory_v2, dict):
                route_snapshot["regime_advisory"] = runtime_advisory_v2
                route_snapshot["regime_eval_ts"] = ctx._parse_numeric(
                    runtime_advisory_v2.get("analysisAnchorEpoch"),
                    fallback=route_eval_ts,
                ) or route_eval_ts
            else:
                route_snapshot["regime_eval_ts"] = route_eval_ts

        force_shadow_refresh = shadow_regime_manager.should_force_shadow_refresh(
            symbol=symbol,
            cfg=cfg,
            route_eval_ts=route_eval_ts,
            parse_numeric=ctx._parse_numeric,
            router_flag=ctx._router_flag,
            router_max_route_age_seconds=ctx._router_max_route_age_seconds,
        )
        if force_shadow_refresh:
            pre_route_candidate_regime = ctx.detect_regime(snapshot, regime_cfg)
            ctx._record_shadow_regime_metrics(
                symbol=symbol,
                snapshot=snapshot,
                candidate_regime=pre_route_candidate_regime,
                cfg=cfg,
                update_regime_shadow_state=ctx.update_regime_shadow_state,
                logger=ctx.logger,
            )
            shadow_updated_pre_route = True

        try:
            route_quality = ctx.load_route_quality_report_cached(
                state_dir=ctx.STATE_DIR,
                cfg=cfg,
                now_epoch=route_eval_ts,
            )
            if isinstance(route_quality, dict):
                route_snapshot["route_quality"] = route_quality
        except Exception:
            # Route quality gates are conservative extras; ignore transient scorecard issues.
            pass

    entry_route = ctx.resolve_entry_route(
        cfg=cfg,
        symbol=symbol,
        snapshot=route_snapshot,
        default_strategy=strategy_mode,
        shadow_state=rt._shadow_regime_state,
    )
    route_strategy = entry_contracts._normalize_strategy(
        entry_route.get("effective_strategy", strategy_mode),
        fallback=entry_contracts._normalize_strategy(strategy_mode, fallback="mean_reversion"),
    )
    effective_strategy = route_strategy
    ctx._record_route_metadata(
        symbol=symbol,
        route=entry_route,
        parse_numeric=ctx._parse_numeric,
    )
    in_position = entry is not None
    active_exit_policy = entry_contracts._exit_policy_for_route(effective_strategy)
    if in_position:
        # Open positions keep their entry route + exit policy; do not remap each cycle.
        effective_strategy = entry_contracts._active_route_for_position(symbol, "mean_reversion")
        active_exit_policy = entry_contracts._active_exit_policy_for_position(symbol, effective_strategy)
        if rt._last_effective_strategy.get(symbol) != effective_strategy:
            rt._last_effective_strategy[symbol] = effective_strategy
            rt._metrics_dirty = True
        if rt._last_effective_route.get(symbol) != effective_strategy:
            rt._last_effective_route[symbol] = effective_strategy
            rt._metrics_dirty = True
        if rt._last_fallback_reason.get(symbol) != "open_position_exit_policy_locked":
            rt._last_fallback_reason[symbol] = "open_position_exit_policy_locked"
            rt._metrics_dirty = True
    min_atr = volatility_cfg.get(
        "min_atr",
        regime_cfg.get("min_atr", cfg.get("min_atr", 0.003)),
    )
    min_atr_pct = volatility_cfg.get("min_atr_pct", min_atr)
    effective_min_atr = max(min_atr, min_atr_pct)
    buy_zone_low, buy_zone_high = regime_cfg.get("preferred_buy_zone", [0.05, 0.30])
    min_z_score = regime_cfg.get("min_z_score", -1.5)
    min_score_to_buy = float(
        regime_cfg.get("min_score_to_buy", cfg.get("min_score_to_buy", 60))
    )
    max_negative_z_score = profit_cfg.get(
        "max_negative_z_score",
        regime_cfg.get("max_negative_z_score", -3.0),
    )
    blocked_regimes = set(
        regime_cfg.get(
            "hard_blocked_regimes",
            regime_cfg.get("blocked_regimes", ["unknown"]),
        )
    )
    scalper_blocked_regimes = set()
    raw_scalper_blocked_regimes = scalper_cfg.get("blocked_regimes", set())
    if isinstance(raw_scalper_blocked_regimes, (set, list, tuple)):
        for raw in raw_scalper_blocked_regimes:
            token = str(raw or "").strip().lower()
            if token:
                scalper_blocked_regimes.add(token)
    route_blocked_regimes = blocked_regimes if effective_strategy == "mean_reversion" else set()

    if effective_strategy == "volatility_scalper":
        regime, score, range_pos, volatility = ctx._compute_scalper_diagnostics(
            snapshot=snapshot,
            price=price,
            momentum=momentum,
            high_24h=high_24h,
            low_24h=low_24h,
            atr=atr,
            z_score=z_score,
            regime_cfg=regime_cfg,
            scalper_cfg=scalper_cfg,
            parse_numeric=ctx._parse_numeric,
        )
    elif effective_strategy == "trend_pullback":
        regime, score, range_pos, volatility = ctx.compute_trend_score_bundle(
            snapshot=snapshot,
            price=price,
            momentum=momentum,
            high_24h=high_24h,
            low_24h=low_24h,
            atr=atr,
        )
    elif effective_strategy == "breakout_momentum":
        regime, score, range_pos, volatility = ctx.compute_breakout_score_bundle(
            snapshot=snapshot,
            price=price,
            momentum=momentum,
            high_24h=high_24h,
            low_24h=low_24h,
            atr=atr,
        )
    else:
        regime, score, range_pos, volatility = ctx.compute_mr_score_bundle(
            snapshot=snapshot,
            price=price,
            momentum=momentum,
            high_24h=high_24h,
            low_24h=low_24h,
            atr=atr,
            z_score=z_score,
            regime_cfg=regime_cfg,
            parse_numeric=ctx._parse_numeric,
        )
    ctx._record_symbol_metrics(
        symbol=symbol,
        regime=regime,
        score=score,
        volatility=volatility,
        parse_numeric=ctx._parse_numeric,
    )
    if not shadow_updated_pre_route or regime != pre_route_candidate_regime:
        ctx._record_shadow_regime_metrics(
            symbol=symbol,
            snapshot=snapshot,
            candidate_regime=regime,
            cfg=cfg,
            update_regime_shadow_state=ctx.update_regime_shadow_state,
            logger=ctx.logger,
        )
    ctx._flush_metrics_state_if_due()

    if active_exit_policy == rt.EXIT_POLICY_SCALPER:
        sell_signal = ctx._evaluate_scalper_sell(
            symbol=symbol,
            price=price,
            momentum=momentum,
            entry=entry,
            entry_ts=entry_ts,
            atr=atr,
            z_score=z_score,
            scalper_cfg=scalper_cfg,
            parse_numeric=ctx._parse_numeric,
            decision=ctx._decision,
        )
    elif active_exit_policy == rt.EXIT_POLICY_TREND:
        sell_signal = ctx.evaluate_trend_exit(
            symbol=symbol,
            price=price,
            momentum=momentum,
            entry=entry,
            z_score=z_score,
            first_activation=profit_cfg.get("first_activation", 0.02),
            initial_lock=profit_cfg.get("initial_lock", 0.01),
            profit_levels=profit_cfg.get(
                "levels",
                [
                    [0.04, 0.03],
                    [0.05, 0.04],
                    [0.06, 0.05],
                    [0.08, 0.06],
                ],
            ),
            trailing_activation=profit_cfg.get("trailing_activation", 0.10),
            trailing_gap=profit_cfg.get("trailing_gap", 0.02),
            reset_below_activation=profit_cfg.get("reset_below_activation", True),
            max_negative_z_score=max_negative_z_score,
            profit_lock_state=rt._profit_lock,
            peak_pnl_state=rt._peak_pnl,
            entry_price_state=rt._entry_price,
            save_strategy_state=ctx._save_strategy_state,
            decision=ctx._decision,
            logger=ctx.logger,
        )
    elif active_exit_policy == rt.EXIT_POLICY_BREAKOUT:
        sell_signal = ctx.evaluate_breakout_exit(
            symbol=symbol,
            price=price,
            momentum=momentum,
            entry=entry,
            z_score=z_score,
            first_activation=profit_cfg.get("first_activation", 0.02),
            initial_lock=profit_cfg.get("initial_lock", 0.01),
            profit_levels=profit_cfg.get(
                "levels",
                [
                    [0.04, 0.03],
                    [0.05, 0.04],
                    [0.06, 0.05],
                    [0.08, 0.06],
                ],
            ),
            trailing_activation=profit_cfg.get("trailing_activation", 0.10),
            trailing_gap=profit_cfg.get("trailing_gap", 0.02),
            reset_below_activation=profit_cfg.get("reset_below_activation", True),
            max_negative_z_score=max_negative_z_score,
            profit_lock_state=rt._profit_lock,
            peak_pnl_state=rt._peak_pnl,
            entry_price_state=rt._entry_price,
            save_strategy_state=ctx._save_strategy_state,
            decision=ctx._decision,
            logger=ctx.logger,
        )
    else:
        sell_signal = ctx.evaluate_mr_exit(
            symbol=symbol,
            price=price,
            momentum=momentum,
            entry=entry,
            z_score=z_score,
            first_activation=profit_cfg.get("first_activation", 0.02),
            initial_lock=profit_cfg.get("initial_lock", 0.01),
            profit_levels=profit_cfg.get(
                "levels",
                [
                    [0.04, 0.03],
                    [0.05, 0.04],
                    [0.06, 0.05],
                    [0.08, 0.06],
                ],
            ),
            trailing_activation=profit_cfg.get("trailing_activation", 0.10),
            trailing_gap=profit_cfg.get("trailing_gap", 0.02),
            reset_below_activation=profit_cfg.get("reset_below_activation", True),
            max_negative_z_score=max_negative_z_score,
            profit_lock_state=rt._profit_lock,
            peak_pnl_state=rt._peak_pnl,
            entry_price_state=rt._entry_price,
            save_strategy_state=ctx._save_strategy_state,
            decision=ctx._decision,
            logger=ctx.logger,
        )

    # SELL is always allowed to fire while in a position.
    if sell_signal is not None:
        return sell_signal

    if effective_strategy == "observe_only":
        return ctx._decision(symbol, "HOLD", price, momentum, "observe_only_mode")

    if effective_strategy == "volatility_scalper":
        decision = ctx._evaluate_scalper_buy(
            snapshot=snapshot,
            symbol=symbol,
            price=price,
            momentum=momentum,
            trades=trades,
            atr=atr,
            z_score=z_score,
            prev_mom=prev_mom,
            regime=regime,
            score=score,
            range_pos=range_pos,
            blocked_regimes=scalper_blocked_regimes,
            min_trades=min_trades,
            scalper_cfg=scalper_cfg,
            parse_numeric=ctx._parse_numeric,
            decision=ctx._decision,
        )
        return entry_contracts._attach_entry_contract_candidate(
            decision=decision,
            active_strategy=effective_strategy,
            route=entry_route,
            parse_numeric=ctx._parse_numeric,
        )

    if effective_strategy == "trend_pullback":
        decision = ctx._evaluate_trend_pullback_buy(
            snapshot=snapshot,
            symbol=symbol,
            price=price,
            momentum=momentum,
            trades=trades,
            high_24h=high_24h,
            low_24h=low_24h,
            atr=atr,
            vwap=vwap,
            z_score=z_score,
            prev_mom=prev_mom,
            min_trades=min_trades,
            min_atr=effective_min_atr,
            min_score_to_buy=min_score_to_buy,
            blocked_regimes=route_blocked_regimes,
            regime=regime,
            score=score,
            range_pos=range_pos,
            cfg=cfg,
            decision=ctx._decision,
        )
        return entry_contracts._attach_entry_contract_candidate(
            decision=decision,
            active_strategy=effective_strategy,
            route=entry_route,
            parse_numeric=ctx._parse_numeric,
        )

    if effective_strategy == "breakout_momentum":
        decision = ctx._evaluate_breakout_momentum_buy(
            snapshot=snapshot,
            symbol=symbol,
            price=price,
            momentum=momentum,
            trades=trades,
            high_24h=high_24h,
            low_24h=low_24h,
            atr=atr,
            vwap=vwap,
            z_score=z_score,
            prev_mom=prev_mom,
            min_trades=min_trades,
            min_atr=effective_min_atr,
            min_score_to_buy=min_score_to_buy,
            blocked_regimes=route_blocked_regimes,
            regime=regime,
            score=score,
            range_pos=range_pos,
            cfg=cfg,
            decision=ctx._decision,
        )
        return entry_contracts._attach_entry_contract_candidate(
            decision=decision,
            active_strategy=effective_strategy,
            route=entry_route,
            parse_numeric=ctx._parse_numeric,
        )

    decision = ctx._evaluate_buy(
        snapshot=snapshot,
        symbol=symbol,
        price=price,
        momentum=momentum,
        trades=trades,
        high_24h=high_24h,
        low_24h=low_24h,
        atr=atr,
        vwap=vwap,
        z_score=z_score,
        prev_mom=prev_mom,
        min_trades=min_trades,
        min_atr=effective_min_atr,
        buy_zone_low=buy_zone_low,
        buy_zone_high=buy_zone_high,
        min_z_score=min_z_score,
        min_score_to_buy=min_score_to_buy,
        blocked_regimes=route_blocked_regimes,
        regime=regime,
        score=score,
        range_pos=range_pos,
        decision=ctx._decision,
    )
    return entry_contracts._attach_entry_contract_candidate(
        decision=decision,
        active_strategy=effective_strategy,
        route=entry_route,
        parse_numeric=ctx._parse_numeric,
    )


def _router_flag(cfg: dict, key: str, default: bool = False) -> bool:
    return _router_flag_impl(cfg, key, default)


def _configured_regime_for_symbol(cfg: dict, symbol: str) -> str:
    return _configured_regime_for_symbol_impl(cfg, symbol)


def _parse_numeric(value, fallback=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _router_max_route_age_seconds(cfg: dict, parse_numeric=None) -> float:
    if parse_numeric is None:
        parse_numeric = _parse_numeric
    router = _router_cfg_impl(cfg)
    raw = router.get("auto_max_route_age_seconds")
    value = parse_numeric(raw, fallback=rt.DEFAULT_AUTO_MAX_ROUTE_AGE_SECONDS)
    if value is None or value <= 0:
        return float(rt.DEFAULT_AUTO_MAX_ROUTE_AGE_SECONDS)
    return max(float(value), 60.0)


def _advisory_has_required_fields(advisory: dict) -> bool:
    return _advisory_has_required_fields_impl(advisory)


def _decision(symbol, action, price, momentum, reason, *, logger):
    return build_decision_payload(
        symbol=symbol,
        action=action,
        price=price,
        momentum=momentum,
        reason=reason,
        logger=logger,
        record_buy_block_gate=_record_buy_block_gate,
    )


def _compute_buy_diagnostics(
    snapshot,
    price,
    momentum,
    high_24h,
    low_24h,
    atr,
    z_score,
    regime_cfg,
    parse_numeric,
):
    return _compute_buy_diagnostics_impl(
        snapshot=snapshot,
        price=price,
        momentum=momentum,
        high_24h=high_24h,
        low_24h=low_24h,
        atr=atr,
        z_score=z_score,
        regime_cfg=regime_cfg,
        parse_numeric=parse_numeric,
    )


def _resolve_scalper_config(cfg, parse_numeric):
    return _resolve_scalper_config_impl(cfg, parse_numeric)


def _strategy_for_symbol(cfg, symbol, scalper_cfg):
    return _strategy_for_symbol_impl(cfg, symbol, scalper_cfg)


def _compute_scalper_diagnostics(
    snapshot,
    price,
    momentum,
    high_24h,
    low_24h,
    atr,
    z_score,
    regime_cfg,
    scalper_cfg,
    parse_numeric,
):
    return _compute_scalper_diagnostics_impl(
        snapshot=snapshot,
        price=price,
        momentum=momentum,
        high_24h=high_24h,
        low_24h=low_24h,
        atr=atr,
        z_score=z_score,
        regime_cfg=regime_cfg,
        scalper_cfg=scalper_cfg,
        parse_numeric=parse_numeric,
    )


def _record_route_metadata(*, symbol: str, route: dict, parse_numeric):
    strategy_metrics.record_route_metadata(symbol=symbol, route=route, parse_numeric=parse_numeric)


def _record_symbol_metrics(symbol, regime, score, volatility, parse_numeric):
    strategy_metrics.record_symbol_metrics(
        symbol=symbol,
        regime=regime,
        score=score,
        volatility=volatility,
        parse_numeric=parse_numeric,
        record_symbol_metrics_impl=_record_symbol_metrics_impl,
    )


def _record_buy_block_gate(*, symbol, action, reason):
    strategy_metrics.record_buy_block_gate(
        symbol=symbol,
        action=action,
        reason=reason,
        normalize_strategy=entry_contracts._normalize_strategy,
    )


def _flush_metrics_state_if_due(save_strategy_state, force=False):
    strategy_metrics.flush_metrics_state_if_due(save_strategy_state=save_strategy_state, force=force)


def _record_shadow_regime_metrics(*, symbol, snapshot, candidate_regime, cfg, update_regime_shadow_state, logger):
    shadow_regime_manager.record_shadow_regime_metrics(
        symbol=symbol,
        snapshot=snapshot,
        candidate_regime=candidate_regime,
        cfg=cfg,
        update_regime_shadow_state=update_regime_shadow_state,
        logger=logger,
    )


def _evaluate_trend_pullback_buy(
    snapshot,
    symbol,
    price,
    momentum,
    trades,
    high_24h,
    low_24h,
    atr,
    vwap,
    z_score,
    prev_mom,
    min_trades,
    min_atr,
    min_score_to_buy,
    blocked_regimes,
    regime,
    score,
    range_pos,
    cfg,
    decision,
):
    action, reason = evaluate_trend_pullback_route_entry(
        snapshot=snapshot,
        price=price,
        momentum=momentum,
        trades=trades,
        high_24h=high_24h,
        low_24h=low_24h,
        atr=atr,
        vwap=vwap,
        z_score=z_score,
        prev_momentum=prev_mom,
        min_trades=min_trades,
        min_atr=min_atr,
        min_score_to_buy=min_score_to_buy,
        blocked_regimes=blocked_regimes,
        regime=regime,
        score=score,
        range_pos=range_pos,
        cfg=cfg,
    )
    if action == "BUY" or reason == "trend_pullback_momentum_weakening":
        rt._last_momentum[symbol] = momentum
    return decision(symbol, action, price, momentum, reason)


def _evaluate_breakout_momentum_buy(
    snapshot,
    symbol,
    price,
    momentum,
    trades,
    high_24h,
    low_24h,
    atr,
    vwap,
    z_score,
    prev_mom,
    min_trades,
    min_atr,
    min_score_to_buy,
    blocked_regimes,
    regime,
    score,
    range_pos,
    cfg,
    decision,
):
    action, reason = evaluate_breakout_momentum_route_entry(
        snapshot=snapshot,
        price=price,
        momentum=momentum,
        trades=trades,
        high_24h=high_24h,
        low_24h=low_24h,
        atr=atr,
        vwap=vwap,
        z_score=z_score,
        prev_momentum=prev_mom,
        min_trades=min_trades,
        min_atr=min_atr,
        min_score_to_buy=min_score_to_buy,
        blocked_regimes=blocked_regimes,
        regime=regime,
        score=score,
        range_pos=range_pos,
        cfg=cfg,
    )
    if action == "BUY" or reason == "breakout_momentum_weakening":
        rt._last_momentum[symbol] = momentum
    return decision(symbol, action, price, momentum, reason)


def _evaluate_sell(
    *,
    symbol,
    price,
    momentum,
    entry,
    z_score,
    first_activation,
    initial_lock,
    profit_levels,
    trailing_activation,
    trailing_gap,
    reset_below_activation,
    max_negative_z_score,
    save_strategy_state,
    decision,
    logger,
):
    return _evaluate_sell_impl(
        symbol=symbol,
        price=price,
        momentum=momentum,
        entry=entry,
        z_score=z_score,
        first_activation=first_activation,
        initial_lock=initial_lock,
        profit_levels=profit_levels,
        trailing_activation=trailing_activation,
        trailing_gap=trailing_gap,
        reset_below_activation=reset_below_activation,
        max_negative_z_score=max_negative_z_score,
        profit_lock_state=rt._profit_lock,
        peak_pnl_state=rt._peak_pnl,
        entry_price_state=rt._entry_price,
        save_strategy_state=save_strategy_state,
        decision=decision,
        logger=logger,
    )


def _evaluate_scalper_sell(
    *,
    symbol,
    price,
    momentum,
    entry,
    entry_ts,
    atr,
    z_score,
    scalper_cfg,
    parse_numeric,
    decision,
):
    return _evaluate_scalper_sell_impl(
        symbol=symbol,
        price=price,
        momentum=momentum,
        entry=entry,
        entry_ts=entry_ts,
        atr=atr,
        z_score=z_score,
        scalper_cfg=scalper_cfg,
        entry_time_state=rt._entry_time,
        peak_pnl_state=rt._peak_pnl,
        parse_numeric=parse_numeric,
        decision=decision,
    )


def _evaluate_scalper_buy(
    *,
    snapshot,
    symbol,
    price,
    momentum,
    trades,
    atr,
    z_score,
    prev_mom,
    regime,
    score,
    range_pos,
    blocked_regimes,
    min_trades,
    scalper_cfg,
    parse_numeric,
    decision,
):
    data_quality_ok = snapshot.get("data_quality_ok")
    if data_quality_ok is not True:
        reason = snapshot.get("data_quality_reason")
        if not isinstance(reason, str) or not reason.strip():
            reason = "data_quality_missing" if data_quality_ok is None else "data_quality_failed"
        return decision(
            symbol,
            "HOLD",
            price,
            momentum,
            str(reason),
        )

    if regime in blocked_regimes:
        return decision(symbol, "HOLD", price, momentum, f"regime_{regime}")

    required_trades = max(int(scalper_cfg.get("min_trades", 6)), int(min_trades))
    if trades < required_trades:
        return decision(symbol, "HOLD", price, momentum, "scalper_insufficient_trades")

    atr_value = parse_numeric(atr, fallback=None)
    if atr_value is None or atr_value <= 0:
        return decision(symbol, "HOLD", price, momentum, "scalper_missing_volatility")

    min_atr = max(scalper_cfg.get("min_atr", 0.008), 0.0)
    if atr_value < min_atr:
        return decision(symbol, "HOLD", price, momentum, "scalper_volatility_too_low")

    spread_bps = parse_numeric(snapshot.get("spread_bps"), fallback=None)
    max_spread_bps = max(scalper_cfg.get("max_spread_bps", 120.0), 0.0)
    if spread_bps is not None and spread_bps > max_spread_bps:
        return decision(symbol, "HOLD", price, momentum, "scalper_spread_too_wide")

    max_range_pos = scalper_cfg.get("max_range_pos")
    if max_range_pos is not None and range_pos is not None and range_pos > max_range_pos:
        return decision(symbol, "HOLD", price, momentum, "scalper_too_extended")

    if z_score is None:
        vwap = parse_numeric(snapshot.get("vwap"), fallback=None)
        if vwap is not None and atr_value > 0:
            z_score = (price - vwap) / atr_value

    entry_z_score_max = parse_numeric(
        scalper_cfg.get("entry_z_score_max"),
        fallback=-0.1,
    )
    if z_score is not None and entry_z_score_max is not None and z_score > entry_z_score_max:
        return decision(symbol, "HOLD", price, momentum, "scalper_wait_for_pullback")

    min_momentum = parse_numeric(
        scalper_cfg.get("min_momentum"),
        fallback=0.2,
    )
    if min_momentum is not None and momentum < min_momentum:
        return decision(symbol, "HOLD", price, momentum, "scalper_momentum_not_ready")

    min_score = max(float(scalper_cfg.get("min_score_to_buy", 55.0)), 0.0)
    if score < min_score:
        return decision(symbol, "HOLD", price, momentum, "scalper_score_below_threshold")

    if prev_mom is not None and momentum < prev_mom:
        rt._last_momentum[symbol] = momentum
        return decision(symbol, "HOLD", price, momentum, "scalper_momentum_weakening")

    rt._last_momentum[symbol] = momentum
    return decision(symbol, "BUY", price, momentum, "volatility_scalper_entry")


def _evaluate_buy(
    *,
    snapshot,
    symbol,
    price,
    momentum,
    trades,
    high_24h,
    low_24h,
    atr,
    vwap,
    z_score,
    prev_mom,
    min_trades,
    min_atr,
    buy_zone_low,
    buy_zone_high,
    min_z_score,
    min_score_to_buy,
    blocked_regimes,
    regime,
    score,
    range_pos,
    decision,
):
    return evaluate_mean_reversion_entry(
        snapshot=snapshot,
        symbol=symbol,
        price=price,
        momentum=momentum,
        trades=trades,
        high_24h=high_24h,
        low_24h=low_24h,
        atr=atr,
        vwap=vwap,
        z_score=z_score,
        prev_mom=prev_mom,
        min_trades=min_trades,
        min_atr=min_atr,
        buy_zone_low=buy_zone_low,
        buy_zone_high=buy_zone_high,
        min_z_score=min_z_score,
        min_score_to_buy=min_score_to_buy,
        blocked_regimes=blocked_regimes,
        regime=regime,
        score=score,
        range_pos=range_pos,
        last_momentum_state=rt._last_momentum,
        decision=decision,
    )
