from __future__ import annotations

import sys
import time
from pathlib import Path

from strategy.entry_contracts import (
    clear_entry_contract,
    confirm_entry as _confirm_entry_impl,
    confirm_exit as _confirm_exit_impl,
    stage_entry_contract,
)
from strategy.exits.breakout_exit import evaluate_breakout_exit
from strategy.exits.mr_exit import evaluate_mr_exit
from strategy.exits.trend_exit import evaluate_trend_exit
from strategy.regime import detect_regime
from strategy.regime_engine import normalize_shadow_state, update_regime_shadow_state
from strategy.regime_engine_v2 import evaluate_regime_unified
from strategy.regime_router import resolve_entry_route
from strategy.route_metadata import state_map as _route_metadata_state_map
from strategy.route_quality import load_route_quality_report_cached
from strategy.route_scoring.breakout_score import compute_breakout_score_bundle
from strategy.route_scoring.mr_score import compute_mr_score_bundle
from strategy.route_scoring.trend_score import compute_trend_score_bundle
from strategy.runtime_state_object import StrategyRuntimeState
from strategy.state_io import (
    load_strategy_state as _load_strategy_state_impl,
    paper_state_mtime as _paper_state_mtime_impl,
    save_strategy_state as _save_strategy_state_impl,
    sync_with_broker_state as _sync_with_broker_state_impl,
)
from strategy.strategy_orchestrator import (
    _advisory_has_required_fields,
    _compute_buy_diagnostics,
    _compute_scalper_diagnostics,
    _configured_regime_for_symbol,
    _decision as _decision_impl,
    _evaluate_breakout_momentum_buy,
    _evaluate_buy,
    _evaluate_scalper_buy,
    _evaluate_scalper_sell,
    _evaluate_sell,
    _evaluate_trend_pullback_buy,
    _flush_metrics_state_if_due as _flush_metrics_state_if_due_impl,
    _parse_numeric,
    _record_route_metadata,
    _record_shadow_regime_metrics,
    _record_symbol_metrics,
    _resolve_scalper_config as _resolve_scalper_config_impl,
    _router_flag,
    _router_max_route_age_seconds,
    _strategy_for_symbol,
    evaluate_symbol as _evaluate_symbol_impl,
    generate_decision as _generate_decision_impl,
)
from strategy import strategy_runtime_state as rt
from utils.logger import setup_logger
from utils.runtime_events import append_runtime_event as _append_runtime_event
from utils.state_paths import resolve_state_dir
from utils.state_io import read_json_file, write_json_file

logger = setup_logger("strategy")

STATE_DIR = resolve_state_dir(Path(__file__).resolve().parent.parent / "state")
STRATEGY_STATE_FILE = STATE_DIR / "strategy_state.json"
PAPER_STATE_FILE = STATE_DIR / "paper_state.json"

RUNTIME_STATE = StrategyRuntimeState.from_runtime_module(rt)
RUNTIME_SCALARS = RUNTIME_STATE.scalars

# Backward-compatible exported state names for legacy callers/tests.
_COMPAT_RUNTIME_EXPORTS = {
    "_route_metadata_maps": "ROUTE_METADATA_MAPS",
    "_last_signal": "_last_signal",
    "_last_sell_price": "_last_sell_price",
    "_entry_price": "_entry_price",
    "_entry_time": "_entry_time",
    "_profit_lock": "_profit_lock",
    "_peak_pnl": "_peak_pnl",
    "_last_momentum": "_last_momentum",
    "_last_regime": "_last_regime",
    "_last_score": "_last_score",
    "_last_volatility": "_last_volatility",
    "_last_configured_regime": "_last_configured_regime",
    "_last_detected_regime": "_last_detected_regime",
    "_last_detected_regime_confidence": "_last_detected_regime_confidence",
    "_last_detected_regime_confidence_label": "_last_detected_regime_confidence_label",
    "_last_detected_regime_stability": "_last_detected_regime_stability",
    "_last_detected_regime_persistence": "_last_detected_regime_persistence",
    "_last_detected_regime_stability_inferred": "_last_detected_regime_stability_inferred",
    "_last_detected_regime_persistence_inferred": "_last_detected_regime_persistence_inferred",
    "_last_regime_data_quality_status": "_last_regime_data_quality_status",
    "_last_regime_key_windows_supported": "_last_regime_key_windows_supported",
    "_last_suggested_regime_v2": "_last_suggested_regime_v2",
    "_last_detection_source": "_last_detection_source",
    "_last_detection_timestamp_epoch": "_last_detection_timestamp_epoch",
    "_last_effective_strategy": "_last_effective_strategy",
    "_last_effective_route": "_last_effective_route",
    "_last_route_eval_ts": "_last_route_eval_ts",
    "_last_regime_eval_ts": "_last_regime_eval_ts",
    "_last_auto_fallback_reason": "_last_auto_fallback_reason",
    "_last_fallback_reason": "_last_fallback_reason",
    "_last_ready_for_non_mr_route": "_last_ready_for_non_mr_route",
    "_last_non_mr_ready_reason": "_last_non_mr_ready_reason",
    "_last_route_readiness_state": "_last_route_readiness_state",
    "_last_route_timestamp_age_seconds": "_last_route_timestamp_age_seconds",
    "_last_route_timestamp_fresh": "_last_route_timestamp_fresh",
    "_last_shadow_continuity_state": "_last_shadow_continuity_state",
    "_last_shadow_age_seconds": "_last_shadow_age_seconds",
    "_last_failed_gates": "_last_failed_gates",
    "_last_decision_diagnostics": "_last_decision_diagnostics",
    "_last_buy_block_reason": "_last_buy_block_reason",
    "_last_buy_block_route": "_last_buy_block_route",
    "_buy_block_counts_by_symbol": "_buy_block_counts_by_symbol",
    "_buy_block_counts_by_symbol_route": "_buy_block_counts_by_symbol_route",
    "_entry_route": "_entry_route",
    "_entry_regime": "_entry_regime",
    "_exit_policy": "_exit_policy",
    "_entry_confidence": "_entry_confidence",
    "_entry_timestamp": "_entry_timestamp",
    "_entry_route_eval_ts": "_entry_route_eval_ts",
    "_entry_regime_eval_ts": "_entry_regime_eval_ts",
    "_pending_entry_contract": "_pending_entry_contract",
    "_shadow_regime_state": "_shadow_regime_state",
}


def __getattr__(name: str):
    runtime_name = _COMPAT_RUNTIME_EXPORTS.get(name)
    if runtime_name is None:
        raise AttributeError(name)
    return getattr(rt, runtime_name)


def _decision(symbol, action, price, momentum, reason):
    return _decision_impl(symbol, action, price, momentum, reason, logger=logger)


def append_runtime_event(event_name: str, **payload):
    _append_runtime_event(event_name, service="strategy", **payload)


def _resolve_scalper_config(cfg):
    return _resolve_scalper_config_impl(cfg, _parse_numeric)


def _flush_metrics_state_if_due(force=False):
    return _flush_metrics_state_if_due_impl(save_strategy_state=_save_strategy_state, force=force)


def _save_strategy_state():
    RUNTIME_STATE.persist_to_runtime()
    rt._last_metrics_flush_at = _save_strategy_state_impl(
        state_dir=STATE_DIR,
        strategy_state_file=STRATEGY_STATE_FILE,
        write_json_file=write_json_file,
        state_maps={
            "entry_price": rt._entry_price,
            "entry_time": rt._entry_time,
            "entry_route": rt._entry_route,
            "entry_regime": rt._entry_regime,
            "exit_policy": rt._exit_policy,
            "entry_confidence": rt._entry_confidence,
            "entry_timestamp": rt._entry_timestamp,
            "entry_route_eval_ts": rt._entry_route_eval_ts,
            "entry_regime_eval_ts": rt._entry_regime_eval_ts,
            "profit_lock": rt._profit_lock,
            "peak_pnl": rt._peak_pnl,
            "last_signal": rt._last_signal,
            "last_momentum": rt._last_momentum,
            "last_regime": rt._last_regime,
            "last_score": rt._last_score,
            "last_volatility": rt._last_volatility,
            "last_buy_block_reason": rt._last_buy_block_reason,
            "last_buy_block_route": rt._last_buy_block_route,
            "buy_block_counts_by_symbol": rt._buy_block_counts_by_symbol,
            "buy_block_counts_by_symbol_route": rt._buy_block_counts_by_symbol_route,
            **_route_metadata_state_map(rt.ROUTE_METADATA_MAPS),
        },
        shadow_regime_state=rt._shadow_regime_state,
    )
    rt._metrics_dirty = False
    RUNTIME_STATE.hydrate_from_runtime()


def _load_strategy_state():
    _load_strategy_state_impl(
        strategy_state_file=STRATEGY_STATE_FILE,
        read_json_file=read_json_file,
        normalize_shadow_state=normalize_shadow_state,
        state_maps={
            "entry_price": rt._entry_price,
            "entry_time": rt._entry_time,
            "entry_route": rt._entry_route,
            "entry_regime": rt._entry_regime,
            "exit_policy": rt._exit_policy,
            "entry_confidence": rt._entry_confidence,
            "entry_timestamp": rt._entry_timestamp,
            "entry_route_eval_ts": rt._entry_route_eval_ts,
            "entry_regime_eval_ts": rt._entry_regime_eval_ts,
            "profit_lock": rt._profit_lock,
            "peak_pnl": rt._peak_pnl,
            "last_signal": rt._last_signal,
            "last_momentum": rt._last_momentum,
            "last_regime": rt._last_regime,
            "last_score": rt._last_score,
            "last_volatility": rt._last_volatility,
            "last_buy_block_reason": rt._last_buy_block_reason,
            "last_buy_block_route": rt._last_buy_block_route,
            "buy_block_counts_by_symbol": rt._buy_block_counts_by_symbol,
            "buy_block_counts_by_symbol_route": rt._buy_block_counts_by_symbol_route,
            **_route_metadata_state_map(rt.ROUTE_METADATA_MAPS),
        },
        shadow_regime_state=rt._shadow_regime_state,
        logger=logger,
    )
    RUNTIME_STATE.hydrate_from_runtime()


def confirm_entry(
    symbol: str,
    price: float,
    *,
    entry_route: str | None = None,
    entry_regime: str | None = None,
    exit_policy: str | None = None,
    entry_confidence: float | None = None,
    entry_timestamp: float | None = None,
    route_eval_ts: float | None = None,
    regime_eval_ts: float | None = None,
):
    _confirm_entry_impl(
        symbol=symbol,
        price=price,
        parse_numeric=_parse_numeric,
        save_strategy_state=_save_strategy_state,
        entry_route=entry_route,
        entry_regime=entry_regime,
        exit_policy=exit_policy,
        entry_confidence=entry_confidence,
        entry_timestamp=entry_timestamp,
        route_eval_ts=route_eval_ts,
        regime_eval_ts=regime_eval_ts,
    )


def confirm_exit(symbol: str, price: float):
    _confirm_exit_impl(
        symbol=symbol,
        price=price,
        route_metadata_maps=rt.ROUTE_METADATA_MAPS,
        save_strategy_state=_save_strategy_state,
    )


def set_runtime_scalars_for_compat(
    *,
    synced: bool | None = None,
    last_paper_state_mtime: float | None = None,
    metrics_dirty: bool | None = None,
    last_metrics_flush_at: float | None = None,
):
    if synced is not None:
        RUNTIME_SCALARS.synced = bool(synced)
    if last_paper_state_mtime is not None:
        RUNTIME_SCALARS.last_paper_state_mtime = float(last_paper_state_mtime)
    if metrics_dirty is not None:
        RUNTIME_SCALARS.metrics_dirty = bool(metrics_dirty)
    if last_metrics_flush_at is not None:
        RUNTIME_SCALARS.last_metrics_flush_at = float(last_metrics_flush_at)
    RUNTIME_STATE.persist_to_runtime()


def evaluate_symbol(snapshot: dict, cfg: dict) -> dict:
    RUNTIME_STATE.persist_to_runtime()
    result = _evaluate_symbol_impl(
        snapshot,
        cfg,
        ctx=sys.modules[__name__],
        runtime_state=RUNTIME_STATE,
    )
    RUNTIME_STATE.hydrate_from_runtime()
    return result


def generate_decision(snapshot: dict, cfg: dict) -> dict:
    RUNTIME_STATE.persist_to_runtime()
    result = _generate_decision_impl(
        snapshot,
        cfg,
        ctx=sys.modules[__name__],
        runtime_state=RUNTIME_STATE,
    )
    RUNTIME_STATE.hydrate_from_runtime()
    return result


_load_strategy_state()
