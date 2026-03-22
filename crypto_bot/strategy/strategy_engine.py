import time
from pathlib import Path

from strategy.breakout_momentum import evaluate_breakout_momentum_entry
from strategy.diagnostics import (
    compute_buy_diagnostics as _compute_buy_diagnostics_impl,
    compute_scalper_diagnostics as _compute_scalper_diagnostics_impl,
    record_symbol_metrics as _record_symbol_metrics_impl,
)
from strategy.route_quality import load_route_quality_report_cached
from strategy.regime_engine import normalize_shadow_state, update_regime_shadow_state
from strategy.regime_engine_v2 import evaluate_regime_unified
from strategy.regime_router import resolve_entry_route
from strategy.regime import detect_regime
from strategy.routing import (
    advisory_has_required_fields as _advisory_has_required_fields_impl,
    configured_regime_for_symbol as _configured_regime_for_symbol_impl,
    resolve_scalper_config as _resolve_scalper_config_impl,
    router_flag as _router_flag_impl,
    strategy_for_symbol as _strategy_for_symbol_impl,
)
from strategy.sell_eval import (
    evaluate_scalper_sell as _evaluate_scalper_sell_impl,
    evaluate_sell as _evaluate_sell_impl,
)
from strategy.state_io import (
    load_strategy_state as _load_strategy_state_impl,
    paper_state_mtime as _paper_state_mtime_impl,
    save_strategy_state as _save_strategy_state_impl,
    sync_with_broker_state as _sync_with_broker_state_impl,
)
from strategy.trend_pullback import evaluate_trend_pullback_entry
from utils.logger import setup_logger
from utils.state_io import read_json_file, write_json_file
from utils.token_regimes import (
    TOKEN_REGIME_AUTO,
)

logger = setup_logger("strategy")

# -----------------------------
# Internal strategy state
# -----------------------------
_last_signal = {}
_last_sell_price = {}
_entry_price = {}
_entry_time = {}
_profit_lock = {}
_peak_pnl = {}
_last_momentum = {}
_last_regime = {}
_last_score = {}
_last_volatility = {}
_last_configured_regime = {}
_last_detected_regime = {}
_last_detected_regime_confidence = {}
_last_detected_regime_confidence_label = {}
_last_detected_regime_stability = {}
_last_detected_regime_persistence = {}
_last_detected_regime_stability_inferred = {}
_last_detected_regime_persistence_inferred = {}
_last_regime_data_quality_status = {}
_last_regime_key_windows_supported = {}
_last_suggested_regime_v2 = {}
_last_detection_source = {}
_last_detection_timestamp_epoch = {}
_last_effective_strategy = {}
_last_effective_route = {}
_last_route_eval_ts = {}
_last_regime_eval_ts = {}
_last_auto_fallback_reason = {}
_last_fallback_reason = {}
_shadow_regime_state = {}
_synced = False
_last_paper_state_mtime = None
_metrics_dirty = False
_last_metrics_flush_at = 0.0

METRICS_FLUSH_INTERVAL_SECONDS = 5.0
SCORE_EPSILON = 0.01
VOLATILITY_EPSILON = 1e-6

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
STRATEGY_STATE_FILE = STATE_DIR / "strategy_state.json"
PAPER_STATE_FILE = STATE_DIR / "paper_state.json"


# ============================================================
# STATE SYNC
# ============================================================

def _sync_with_broker_state():
    _sync_with_broker_state_impl(
        paper_state_file=PAPER_STATE_FILE,
        read_json_file=read_json_file,
        parse_numeric=_parse_numeric,
        entry_price=_entry_price,
        entry_time=_entry_time,
        profit_lock=_profit_lock,
        peak_pnl=_peak_pnl,
        last_momentum=_last_momentum,
        last_signal=_last_signal,
        metadata_maps=(
            _last_regime,
            _last_score,
            _last_volatility,
            _last_configured_regime,
            _last_detected_regime,
            _last_detected_regime_confidence,
            _last_detected_regime_confidence_label,
            _last_detected_regime_stability,
            _last_detected_regime_persistence,
            _last_detected_regime_stability_inferred,
            _last_detected_regime_persistence_inferred,
            _last_regime_data_quality_status,
            _last_regime_key_windows_supported,
            _last_suggested_regime_v2,
            _last_detection_source,
            _last_detection_timestamp_epoch,
            _last_effective_strategy,
            _last_effective_route,
            _last_route_eval_ts,
            _last_regime_eval_ts,
            _last_auto_fallback_reason,
            _last_fallback_reason,
        ),
        save_strategy_state=_save_strategy_state,
        logger=logger,
    )


def _paper_state_mtime():
    return _paper_state_mtime_impl(PAPER_STATE_FILE)


def _sync_with_broker_state_if_needed(force: bool = False):
    global _synced, _last_paper_state_mtime

    current_mtime = _paper_state_mtime()
    if (
        not force
        and _synced
        and current_mtime is not None
        and _last_paper_state_mtime is not None
        and current_mtime == _last_paper_state_mtime
    ):
        return

    _sync_with_broker_state()
    _synced = True
    _last_paper_state_mtime = current_mtime


def evaluate_symbol(snapshot: dict, cfg: dict) -> dict:
    _sync_with_broker_state_if_needed()
    return generate_decision(snapshot, cfg)


def _router_flag(cfg: dict, key: str, default: bool = False) -> bool:
    return _router_flag_impl(cfg, key, default)


def _configured_regime_for_symbol(cfg: dict, symbol: str) -> str:
    return _configured_regime_for_symbol_impl(cfg, symbol)


def _advisory_has_required_fields(advisory: dict) -> bool:
    return _advisory_has_required_fields_impl(advisory)


# ============================================================
# CORE STRATEGY
# ============================================================

def generate_decision(snapshot: dict, cfg: dict) -> dict:

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

    entry = _entry_price.get(symbol)
    prev_mom = _last_momentum.get(symbol)
    entry_ts = _entry_time.get(symbol)

    min_trades = cfg.get("min_trades", 3)
    regime_cfg = cfg.get("market_regime", {})
    volatility_cfg = cfg.get("volatility_filters", {})
    profit_cfg = cfg.get("profit_locks", {})
    scalper_cfg = _resolve_scalper_config(cfg)
    strategy_mode = _strategy_for_symbol(cfg, symbol, scalper_cfg=scalper_cfg)
    configured_regime = _configured_regime_for_symbol(cfg, symbol)
    route_snapshot = dict(snapshot)
    route_eval_ts = time.time()
    route_snapshot["router_eval_ts"] = route_eval_ts
    shadow_updated_pre_route = False
    pre_route_candidate_regime = None

    if configured_regime == TOKEN_REGIME_AUTO:
        existing_advisory = route_snapshot.get("regime_advisory")
        existing_advisory_valid = _advisory_has_required_fields(existing_advisory)

        if existing_advisory_valid:
            route_snapshot["regime_eval_ts"] = (
                _parse_numeric(existing_advisory.get("analysisAnchorEpoch"), fallback=None)
                or _parse_numeric(existing_advisory.get("analysis_anchor_epoch"), fallback=None)
                or _parse_numeric(existing_advisory.get("detectionTimestampEpoch"), fallback=None)
                or _parse_numeric(existing_advisory.get("detection_timestamp_epoch"), fallback=None)
                or route_eval_ts
            )
        else:
            runtime_advisory_v2 = evaluate_regime_unified(
                snapshot=route_snapshot,
                now_epoch=route_eval_ts,
                cfg=cfg,
            )
            if isinstance(runtime_advisory_v2, dict):
                route_snapshot["regime_advisory"] = runtime_advisory_v2
                route_snapshot["regime_eval_ts"] = _parse_numeric(
                    runtime_advisory_v2.get("analysisAnchorEpoch"),
                    fallback=route_eval_ts,
                ) or route_eval_ts
            else:
                route_snapshot["regime_eval_ts"] = route_eval_ts

        if _router_flag(cfg, "auto_use_current_cycle_shadow", False):
            pre_route_candidate_regime = detect_regime(snapshot, regime_cfg)
            _record_shadow_regime_metrics(
                symbol=symbol,
                snapshot=snapshot,
                candidate_regime=pre_route_candidate_regime,
                cfg=cfg,
            )
            shadow_updated_pre_route = True

        try:
            route_quality = load_route_quality_report_cached(
                state_dir=STATE_DIR,
                cfg=cfg,
                now_epoch=route_eval_ts,
            )
            if isinstance(route_quality, dict):
                route_snapshot["route_quality"] = route_quality
        except Exception:
            # Route quality gates are conservative extras; ignore transient scorecard issues.
            pass

    entry_route = resolve_entry_route(
        cfg=cfg,
        symbol=symbol,
        snapshot=route_snapshot,
        default_strategy=strategy_mode,
        shadow_state=_shadow_regime_state,
    )
    effective_strategy = entry_route.get("effective_strategy", strategy_mode)
    _record_route_metadata(symbol, entry_route)
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

    if effective_strategy == "volatility_scalper":
        regime, score, range_pos, volatility = _compute_scalper_diagnostics(
            snapshot=snapshot,
            price=price,
            momentum=momentum,
            high_24h=high_24h,
            low_24h=low_24h,
            atr=atr,
            z_score=z_score,
            regime_cfg=regime_cfg,
            scalper_cfg=scalper_cfg,
        )
    else:
        regime, score, range_pos, volatility = _compute_buy_diagnostics(
            snapshot=snapshot,
            price=price,
            momentum=momentum,
            high_24h=high_24h,
            low_24h=low_24h,
            atr=atr,
            z_score=z_score,
            regime_cfg=regime_cfg,
        )
    _record_symbol_metrics(symbol, regime, score, volatility)
    if not shadow_updated_pre_route or regime != pre_route_candidate_regime:
        _record_shadow_regime_metrics(
            symbol=symbol,
            snapshot=snapshot,
            candidate_regime=regime,
            cfg=cfg,
        )
    _flush_metrics_state_if_due()

    if effective_strategy == "volatility_scalper":
        sell_signal = _evaluate_scalper_sell(
            symbol=symbol,
            price=price,
            momentum=momentum,
            entry=entry,
            entry_ts=entry_ts,
            atr=atr,
            z_score=z_score,
            scalper_cfg=scalper_cfg,
        )
    else:
        sell_signal = _evaluate_sell(
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
        )

    # SELL is always allowed to fire while in a position.
    if sell_signal is not None:
        return sell_signal

    if effective_strategy == "observe_only":
        return _decision(symbol, "HOLD", price, momentum, "observe_only_mode")

    if effective_strategy == "volatility_scalper":
        return _evaluate_scalper_buy(
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
            blocked_regimes=blocked_regimes,
            min_trades=min_trades,
            scalper_cfg=scalper_cfg,
        )

    if effective_strategy == "trend_pullback":
        return _evaluate_trend_pullback_buy(
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
            blocked_regimes=blocked_regimes,
            regime=regime,
            score=score,
            range_pos=range_pos,
            cfg=cfg,
        )

    if effective_strategy == "breakout_momentum":
        return _evaluate_breakout_momentum_buy(
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
            blocked_regimes=blocked_regimes,
            regime=regime,
            score=score,
            range_pos=range_pos,
            cfg=cfg,
        )

    return _evaluate_buy(
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
        blocked_regimes=blocked_regimes,
        regime=regime,
        score=score,
        range_pos=range_pos,
    )


def _record_route_metadata(symbol: str, route: dict):
    global _metrics_dirty

    configured = route.get("configured_regime")
    detected = route.get("detected_regime")
    detected_confidence = _parse_numeric(
        route.get("detected_regime_confidence"),
        fallback=None,
    )
    detected_confidence_label = route.get("detected_regime_confidence_label")
    detected_stability = _parse_numeric(route.get("detected_regime_stability"), fallback=None)
    detected_persistence = _parse_numeric(route.get("detected_regime_persistence"), fallback=None)
    detected_stability_inferred = route.get("detected_regime_stability_inferred")
    detected_persistence_inferred = route.get("detected_regime_persistence_inferred")
    regime_data_quality_status = route.get("regime_data_quality_status")
    regime_key_windows_supported = route.get("regime_key_windows_supported")
    suggested_regime_v2 = route.get("suggested_regime_v2")
    detection_source = route.get("detection_source")
    detection_timestamp_epoch = _parse_numeric(
        route.get("detection_timestamp_epoch"),
        fallback=None,
    )
    effective = route.get("effective_strategy")
    effective_route = route.get("effective_route")
    route_eval_ts = _parse_numeric(route.get("route_eval_ts"), fallback=None)
    regime_eval_ts = _parse_numeric(route.get("regime_eval_ts"), fallback=None)
    fallback_reason = route.get("auto_fallback_reason")
    fallback_reason_v2 = route.get("fallback_reason")
    changed = False

    if isinstance(configured, str) and configured:
        if _last_configured_regime.get(symbol) != configured:
            _last_configured_regime[symbol] = configured
            changed = True
    if isinstance(detected, str) and detected:
        if _last_detected_regime.get(symbol) != detected:
            _last_detected_regime[symbol] = detected
            changed = True
    else:
        if symbol in _last_detected_regime:
            _last_detected_regime.pop(symbol, None)
            changed = True

    if detected_confidence is None:
        if symbol in _last_detected_regime_confidence:
            _last_detected_regime_confidence.pop(symbol, None)
            changed = True
    else:
        if _last_detected_regime_confidence.get(symbol) != detected_confidence:
            _last_detected_regime_confidence[symbol] = detected_confidence
            changed = True

    if isinstance(detected_confidence_label, str) and detected_confidence_label:
        if _last_detected_regime_confidence_label.get(symbol) != detected_confidence_label:
            _last_detected_regime_confidence_label[symbol] = detected_confidence_label
            changed = True
    else:
        if symbol in _last_detected_regime_confidence_label:
            _last_detected_regime_confidence_label.pop(symbol, None)
            changed = True

    if detected_stability is None:
        if symbol in _last_detected_regime_stability:
            _last_detected_regime_stability.pop(symbol, None)
            changed = True
    else:
        if _last_detected_regime_stability.get(symbol) != detected_stability:
            _last_detected_regime_stability[symbol] = detected_stability
            changed = True

    if detected_persistence is None:
        if symbol in _last_detected_regime_persistence:
            _last_detected_regime_persistence.pop(symbol, None)
            changed = True
    else:
        if _last_detected_regime_persistence.get(symbol) != detected_persistence:
            _last_detected_regime_persistence[symbol] = detected_persistence
            changed = True

    if isinstance(detected_stability_inferred, bool):
        if _last_detected_regime_stability_inferred.get(symbol) != detected_stability_inferred:
            _last_detected_regime_stability_inferred[symbol] = detected_stability_inferred
            changed = True
    else:
        if symbol in _last_detected_regime_stability_inferred:
            _last_detected_regime_stability_inferred.pop(symbol, None)
            changed = True

    if isinstance(detected_persistence_inferred, bool):
        if _last_detected_regime_persistence_inferred.get(symbol) != detected_persistence_inferred:
            _last_detected_regime_persistence_inferred[symbol] = detected_persistence_inferred
            changed = True
    else:
        if symbol in _last_detected_regime_persistence_inferred:
            _last_detected_regime_persistence_inferred.pop(symbol, None)
            changed = True

    if isinstance(regime_data_quality_status, str) and regime_data_quality_status:
        if _last_regime_data_quality_status.get(symbol) != regime_data_quality_status:
            _last_regime_data_quality_status[symbol] = regime_data_quality_status
            changed = True
    else:
        if symbol in _last_regime_data_quality_status:
            _last_regime_data_quality_status.pop(symbol, None)
            changed = True

    if isinstance(regime_key_windows_supported, bool):
        if _last_regime_key_windows_supported.get(symbol) != regime_key_windows_supported:
            _last_regime_key_windows_supported[symbol] = regime_key_windows_supported
            changed = True
    else:
        if symbol in _last_regime_key_windows_supported:
            _last_regime_key_windows_supported.pop(symbol, None)
            changed = True

    if isinstance(suggested_regime_v2, str) and suggested_regime_v2:
        if _last_suggested_regime_v2.get(symbol) != suggested_regime_v2:
            _last_suggested_regime_v2[symbol] = suggested_regime_v2
            changed = True
    else:
        if symbol in _last_suggested_regime_v2:
            _last_suggested_regime_v2.pop(symbol, None)
            changed = True

    if isinstance(detection_source, str) and detection_source:
        if _last_detection_source.get(symbol) != detection_source:
            _last_detection_source[symbol] = detection_source
            changed = True
    else:
        if symbol in _last_detection_source:
            _last_detection_source.pop(symbol, None)
            changed = True

    if detection_timestamp_epoch is None:
        if symbol in _last_detection_timestamp_epoch:
            _last_detection_timestamp_epoch.pop(symbol, None)
            changed = True
    else:
        if _last_detection_timestamp_epoch.get(symbol) != detection_timestamp_epoch:
            _last_detection_timestamp_epoch[symbol] = detection_timestamp_epoch
            changed = True

    if isinstance(effective, str) and effective:
        if _last_effective_strategy.get(symbol) != effective:
            _last_effective_strategy[symbol] = effective
            changed = True
    else:
        if symbol in _last_effective_strategy:
            _last_effective_strategy.pop(symbol, None)
            changed = True

    if isinstance(effective_route, str) and effective_route:
        if _last_effective_route.get(symbol) != effective_route:
            _last_effective_route[symbol] = effective_route
            changed = True
    elif isinstance(effective, str) and effective:
        if _last_effective_route.get(symbol) != effective:
            _last_effective_route[symbol] = effective
            changed = True
    else:
        if symbol in _last_effective_route:
            _last_effective_route.pop(symbol, None)
            changed = True

    if route_eval_ts is None:
        if symbol in _last_route_eval_ts:
            _last_route_eval_ts.pop(symbol, None)
            changed = True
    else:
        if _last_route_eval_ts.get(symbol) != route_eval_ts:
            _last_route_eval_ts[symbol] = route_eval_ts
            changed = True

    if regime_eval_ts is None:
        if symbol in _last_regime_eval_ts:
            _last_regime_eval_ts.pop(symbol, None)
            changed = True
    else:
        if _last_regime_eval_ts.get(symbol) != regime_eval_ts:
            _last_regime_eval_ts[symbol] = regime_eval_ts
            changed = True

    if isinstance(fallback_reason, str) and fallback_reason:
        if _last_auto_fallback_reason.get(symbol) != fallback_reason:
            _last_auto_fallback_reason[symbol] = fallback_reason
            changed = True
    else:
        if symbol in _last_auto_fallback_reason:
            _last_auto_fallback_reason.pop(symbol, None)
            changed = True

    if isinstance(fallback_reason_v2, str) and fallback_reason_v2:
        if _last_fallback_reason.get(symbol) != fallback_reason_v2:
            _last_fallback_reason[symbol] = fallback_reason_v2
            changed = True
    elif isinstance(fallback_reason, str) and fallback_reason:
        if _last_fallback_reason.get(symbol) != fallback_reason:
            _last_fallback_reason[symbol] = fallback_reason
            changed = True
    else:
        if symbol in _last_fallback_reason:
            _last_fallback_reason.pop(symbol, None)
            changed = True

    if changed:
        _metrics_dirty = True


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
):
    action, reason = evaluate_trend_pullback_entry(
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
        _last_momentum[symbol] = momentum
    return _decision(symbol, action, price, momentum, reason)


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
):
    action, reason = evaluate_breakout_momentum_entry(
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
        _last_momentum[symbol] = momentum
    return _decision(symbol, action, price, momentum, reason)


def _evaluate_sell(
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
        profit_lock_state=_profit_lock,
        peak_pnl_state=_peak_pnl,
        entry_price_state=_entry_price,
        save_strategy_state=_save_strategy_state,
        decision=_decision,
        logger=logger,
    )


def _evaluate_scalper_sell(
    symbol,
    price,
    momentum,
    entry,
    entry_ts,
    atr,
    z_score,
    scalper_cfg,
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
        entry_time_state=_entry_time,
        peak_pnl_state=_peak_pnl,
        parse_numeric=_parse_numeric,
        decision=_decision,
    )


def _evaluate_scalper_buy(
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
):
    if not snapshot.get("data_quality_ok", True):
        return _decision(
            symbol,
            "HOLD",
            price,
            momentum,
            snapshot.get("data_quality_reason", "data_quality_failed"),
        )

    if regime in blocked_regimes:
        return _decision(symbol, "HOLD", price, momentum, f"regime_{regime}")

    required_trades = max(int(scalper_cfg.get("min_trades", 6)), int(min_trades))
    if trades < required_trades:
        return _decision(symbol, "HOLD", price, momentum, "scalper_insufficient_trades")

    atr_value = _parse_numeric(atr, fallback=None)
    if atr_value is None or atr_value <= 0:
        return _decision(symbol, "HOLD", price, momentum, "scalper_missing_volatility")

    min_atr = max(scalper_cfg.get("min_atr", 0.008), 0.0)
    if atr_value < min_atr:
        return _decision(symbol, "HOLD", price, momentum, "scalper_volatility_too_low")

    spread_bps = _parse_numeric(snapshot.get("spread_bps"), fallback=None)
    max_spread_bps = max(scalper_cfg.get("max_spread_bps", 120.0), 0.0)
    if spread_bps is not None and spread_bps > max_spread_bps:
        return _decision(symbol, "HOLD", price, momentum, "scalper_spread_too_wide")

    max_range_pos = scalper_cfg.get("max_range_pos")
    if max_range_pos is not None and range_pos is not None and range_pos > max_range_pos:
        return _decision(symbol, "HOLD", price, momentum, "scalper_too_extended")

    if z_score is None:
        vwap = _parse_numeric(snapshot.get("vwap"), fallback=None)
        if vwap is not None and atr_value > 0:
            z_score = (price - vwap) / atr_value

    entry_z_score_max = _parse_numeric(
        scalper_cfg.get("entry_z_score_max"),
        fallback=-0.1,
    )
    if z_score is not None and entry_z_score_max is not None and z_score > entry_z_score_max:
        return _decision(symbol, "HOLD", price, momentum, "scalper_wait_for_pullback")

    min_momentum = _parse_numeric(
        scalper_cfg.get("min_momentum"),
        fallback=0.2,
    )
    if min_momentum is not None and momentum < min_momentum:
        return _decision(symbol, "HOLD", price, momentum, "scalper_momentum_not_ready")

    min_score = max(float(scalper_cfg.get("min_score_to_buy", 55.0)), 0.0)
    if score < min_score:
        return _decision(symbol, "HOLD", price, momentum, "scalper_score_below_threshold")

    if prev_mom is not None and momentum < prev_mom:
        _last_momentum[symbol] = momentum
        return _decision(symbol, "HOLD", price, momentum, "scalper_momentum_weakening")

    _last_momentum[symbol] = momentum
    return _decision(symbol, "BUY", price, momentum, "volatility_scalper_entry")


def _evaluate_buy(
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
):
    if not snapshot.get("data_quality_ok", True):
        return _decision(
            symbol,
            "HOLD",
            price,
            momentum,
            snapshot.get("data_quality_reason", "data_quality_failed"),
        )

    if (
        trades < min_trades
        or high_24h <= low_24h
        or vwap is None
        or atr is None
        or atr <= 0
    ):
        return _decision(symbol, "HOLD", price, momentum, "insufficient_data")

    if atr < min_atr:
        return _decision(symbol, "HOLD", price, momentum, "atr_too_low")

    if z_score is None:
        z_score = (price - vwap) / atr

    if regime in blocked_regimes:
        return _decision(symbol, "HOLD", price, momentum, f"regime_{regime}")

    if range_pos is None:
        return _decision(symbol, "HOLD", price, momentum, "insufficient_range_data")

    if range_pos > buy_zone_high:
        return _decision(symbol, "HOLD", price, momentum, "price_above_buy_zone")

    if range_pos < buy_zone_low:
        return _decision(symbol, "HOLD", price, momentum, "price_below_buy_zone")

    if z_score > min_z_score:
        return _decision(symbol, "HOLD", price, momentum, "insufficient_volatility_stretch")

    if score < min_score_to_buy:
        return _decision(symbol, "HOLD", price, momentum, "score_below_threshold")

    if prev_mom is not None and momentum < prev_mom:
        _last_momentum[symbol] = momentum
        return _decision(symbol, "HOLD", price, momentum, "momentum_still_falling")

    _last_momentum[symbol] = momentum
    return _decision(symbol, "BUY", price, momentum, "bear_market_mean_reversion_buy")


# ============================================================
# PERSISTENCE
# ============================================================

def _save_strategy_state():
    global _metrics_dirty, _last_metrics_flush_at
    _last_metrics_flush_at = _save_strategy_state_impl(
        state_dir=STATE_DIR,
        strategy_state_file=STRATEGY_STATE_FILE,
        write_json_file=write_json_file,
        state_maps={
            "entry_price": _entry_price,
            "entry_time": _entry_time,
            "profit_lock": _profit_lock,
            "peak_pnl": _peak_pnl,
            "last_signal": _last_signal,
            "last_momentum": _last_momentum,
            "last_regime": _last_regime,
            "last_score": _last_score,
            "last_volatility": _last_volatility,
            "last_configured_regime": _last_configured_regime,
            "last_detected_regime": _last_detected_regime,
            "last_detected_regime_confidence": _last_detected_regime_confidence,
            "last_detected_regime_confidence_label": _last_detected_regime_confidence_label,
            "last_detected_regime_stability": _last_detected_regime_stability,
            "last_detected_regime_persistence": _last_detected_regime_persistence,
            "last_detected_regime_stability_inferred": _last_detected_regime_stability_inferred,
            "last_detected_regime_persistence_inferred": _last_detected_regime_persistence_inferred,
            "last_regime_data_quality_status": _last_regime_data_quality_status,
            "last_regime_key_windows_supported": _last_regime_key_windows_supported,
            "last_suggested_regime_v2": _last_suggested_regime_v2,
            "last_detection_source": _last_detection_source,
            "last_detection_timestamp_epoch": _last_detection_timestamp_epoch,
            "last_effective_strategy": _last_effective_strategy,
            "last_effective_route": _last_effective_route,
            "last_route_eval_ts": _last_route_eval_ts,
            "last_regime_eval_ts": _last_regime_eval_ts,
            "last_auto_fallback_reason": _last_auto_fallback_reason,
            "last_fallback_reason": _last_fallback_reason,
        },
        shadow_regime_state=_shadow_regime_state,
    )
    _metrics_dirty = False


def _load_strategy_state():
    _load_strategy_state_impl(
        strategy_state_file=STRATEGY_STATE_FILE,
        read_json_file=read_json_file,
        normalize_shadow_state=normalize_shadow_state,
        state_maps={
            "entry_price": _entry_price,
            "entry_time": _entry_time,
            "profit_lock": _profit_lock,
            "peak_pnl": _peak_pnl,
            "last_signal": _last_signal,
            "last_momentum": _last_momentum,
            "last_regime": _last_regime,
            "last_score": _last_score,
            "last_volatility": _last_volatility,
            "last_configured_regime": _last_configured_regime,
            "last_detected_regime": _last_detected_regime,
            "last_detected_regime_confidence": _last_detected_regime_confidence,
            "last_detected_regime_confidence_label": _last_detected_regime_confidence_label,
            "last_detected_regime_stability": _last_detected_regime_stability,
            "last_detected_regime_persistence": _last_detected_regime_persistence,
            "last_detected_regime_stability_inferred": _last_detected_regime_stability_inferred,
            "last_detected_regime_persistence_inferred": _last_detected_regime_persistence_inferred,
            "last_regime_data_quality_status": _last_regime_data_quality_status,
            "last_regime_key_windows_supported": _last_regime_key_windows_supported,
            "last_suggested_regime_v2": _last_suggested_regime_v2,
            "last_detection_source": _last_detection_source,
            "last_detection_timestamp_epoch": _last_detection_timestamp_epoch,
            "last_effective_strategy": _last_effective_strategy,
            "last_effective_route": _last_effective_route,
            "last_route_eval_ts": _last_route_eval_ts,
            "last_regime_eval_ts": _last_regime_eval_ts,
            "last_auto_fallback_reason": _last_auto_fallback_reason,
            "last_fallback_reason": _last_fallback_reason,
        },
        shadow_regime_state=_shadow_regime_state,
        logger=logger,
    )


# ============================================================
# HELPERS
# ============================================================
def confirm_entry(symbol: str, price: float):
    _entry_price[symbol] = price
    _entry_time[symbol] = time.time()
    _profit_lock[symbol] = None
    _peak_pnl[symbol] = 0.0
    _last_signal[symbol] = "BUY"
    _save_strategy_state()


def confirm_exit(symbol: str, price: float):
    _cleanup(symbol, price)
    _save_strategy_state()


def _cleanup(symbol, price):
    _last_sell_price[symbol] = price
    _entry_price.pop(symbol, None)
    _entry_time.pop(symbol, None)
    _profit_lock.pop(symbol, None)
    _peak_pnl.pop(symbol, None)
    _last_signal.pop(symbol, None)
    _last_momentum.pop(symbol, None)
    _last_regime.pop(symbol, None)
    _last_score.pop(symbol, None)
    _last_volatility.pop(symbol, None)
    _last_configured_regime.pop(symbol, None)
    _last_detected_regime.pop(symbol, None)
    _last_detected_regime_confidence.pop(symbol, None)
    _last_detected_regime_confidence_label.pop(symbol, None)
    _last_detected_regime_stability.pop(symbol, None)
    _last_detected_regime_persistence.pop(symbol, None)
    _last_detected_regime_stability_inferred.pop(symbol, None)
    _last_detected_regime_persistence_inferred.pop(symbol, None)
    _last_regime_data_quality_status.pop(symbol, None)
    _last_regime_key_windows_supported.pop(symbol, None)
    _last_suggested_regime_v2.pop(symbol, None)
    _last_detection_source.pop(symbol, None)
    _last_detection_timestamp_epoch.pop(symbol, None)
    _last_effective_strategy.pop(symbol, None)
    _last_effective_route.pop(symbol, None)
    _last_route_eval_ts.pop(symbol, None)
    _last_regime_eval_ts.pop(symbol, None)
    _last_auto_fallback_reason.pop(symbol, None)
    _last_fallback_reason.pop(symbol, None)


def _decision(symbol, action, price, momentum, reason):
    logger.info(f"{symbol} -> {action} | reason={reason}")
    payload = {
        "symbol": symbol,
        "action": action,
        "price": price,
        "momentum": momentum,
        "reason": reason,
    }
    if symbol in _last_regime:
        payload["regime"] = _last_regime[symbol]
    if symbol in _last_score:
        payload["score"] = _last_score[symbol]
    if symbol in _last_volatility:
        payload["volatility"] = _last_volatility[symbol]
    if symbol in _last_configured_regime:
        payload["configured_regime"] = _last_configured_regime[symbol]
    if symbol in _last_detected_regime:
        payload["detected_regime"] = _last_detected_regime[symbol]
    if symbol in _last_detected_regime_confidence:
        payload["detected_regime_confidence"] = _last_detected_regime_confidence[symbol]
    if symbol in _last_detected_regime_confidence_label:
        payload["detected_regime_confidence_label"] = _last_detected_regime_confidence_label[symbol]
    if symbol in _last_detected_regime_stability:
        payload["detected_regime_stability"] = _last_detected_regime_stability[symbol]
    if symbol in _last_detected_regime_persistence:
        payload["detected_regime_persistence"] = _last_detected_regime_persistence[symbol]
    if symbol in _last_detected_regime_stability_inferred:
        payload["detected_regime_stability_inferred"] = _last_detected_regime_stability_inferred[symbol]
    if symbol in _last_detected_regime_persistence_inferred:
        payload["detected_regime_persistence_inferred"] = _last_detected_regime_persistence_inferred[symbol]
    if symbol in _last_regime_data_quality_status:
        payload["regime_data_quality_status"] = _last_regime_data_quality_status[symbol]
    if symbol in _last_regime_key_windows_supported:
        payload["regime_key_windows_supported"] = _last_regime_key_windows_supported[symbol]
    if symbol in _last_suggested_regime_v2:
        payload["suggested_regime_v2"] = _last_suggested_regime_v2[symbol]
    if symbol in _last_detection_source:
        payload["detection_source"] = _last_detection_source[symbol]
    if symbol in _last_detection_timestamp_epoch:
        payload["detection_timestamp_epoch"] = _last_detection_timestamp_epoch[symbol]
    if symbol in _last_effective_strategy:
        payload["effective_strategy"] = _last_effective_strategy[symbol]
    if symbol in _last_effective_route:
        payload["effective_route"] = _last_effective_route[symbol]
    if symbol in _last_route_eval_ts:
        payload["route_eval_ts"] = _last_route_eval_ts[symbol]
    if symbol in _last_regime_eval_ts:
        payload["regime_eval_ts"] = _last_regime_eval_ts[symbol]
    if symbol in _last_auto_fallback_reason:
        payload["auto_fallback_reason"] = _last_auto_fallback_reason[symbol]
    if symbol in _last_fallback_reason:
        payload["fallback_reason"] = _last_fallback_reason[symbol]
    return payload


def _parse_numeric(value, fallback=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _compute_buy_diagnostics(
    snapshot,
    price,
    momentum,
    high_24h,
    low_24h,
    atr,
    z_score,
    regime_cfg,
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
        parse_numeric=_parse_numeric,
    )


def _resolve_scalper_config(cfg):
    return _resolve_scalper_config_impl(cfg, _parse_numeric)


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
        parse_numeric=_parse_numeric,
    )


def _record_symbol_metrics(symbol, regime, score, volatility):
    global _metrics_dirty
    changed = _record_symbol_metrics_impl(
        symbol=symbol,
        regime=regime,
        score=score,
        volatility=volatility,
        last_regime_state=_last_regime,
        last_score_state=_last_score,
        last_volatility_state=_last_volatility,
        parse_numeric=_parse_numeric,
        score_epsilon=SCORE_EPSILON,
        volatility_epsilon=VOLATILITY_EPSILON,
    )

    if changed:
        _metrics_dirty = True


def _record_shadow_regime_metrics(*, symbol, snapshot, candidate_regime, cfg):
    global _metrics_dirty

    shadow_row, changed = update_regime_shadow_state(
        symbol=symbol,
        snapshot=snapshot,
        candidate_regime=candidate_regime,
        shadow_state=_shadow_regime_state,
        cfg=cfg,
    )
    if not changed:
        return

    _metrics_dirty = True
    if shadow_row.get("switched"):
        logger.info(
            f"REGIME_SHADOW {symbol} | "
            f"candidate={shadow_row['candidate_regime']} "
            f"stable={shadow_row['stable_regime']} "
            f"conf={shadow_row['confidence']:.3f} "
            f"confirmations={shadow_row['confirmations']} "
            f"switched=1"
        )
    else:
        logger.debug(
            f"REGIME_SHADOW {symbol} | "
            f"candidate={shadow_row['candidate_regime']} "
            f"stable={shadow_row['stable_regime']} "
            f"conf={shadow_row['confidence']:.3f} "
            f"confirmations={shadow_row['confirmations']} "
            f"switched=0"
        )


def _flush_metrics_state_if_due(force=False):
    if not _metrics_dirty:
        return

    now = time.time()
    if not force and (now - _last_metrics_flush_at) < METRICS_FLUSH_INTERVAL_SECONDS:
        return

    _save_strategy_state()



_load_strategy_state()
