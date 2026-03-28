from __future__ import annotations


# -----------------------------
# Internal strategy state
# -----------------------------
_last_signal: dict = {}
_last_sell_price: dict = {}
_entry_price: dict = {}
_entry_time: dict = {}
_profit_lock: dict = {}
_peak_pnl: dict = {}
_last_momentum: dict = {}
_last_regime: dict = {}
_last_score: dict = {}
_last_volatility: dict = {}
_last_configured_regime: dict = {}
_last_detected_regime: dict = {}
_last_detected_regime_confidence: dict = {}
_last_detected_regime_confidence_label: dict = {}
_last_detected_regime_stability: dict = {}
_last_detected_regime_persistence: dict = {}
_last_detected_regime_stability_inferred: dict = {}
_last_detected_regime_persistence_inferred: dict = {}
_last_regime_data_quality_status: dict = {}
_last_regime_key_windows_supported: dict = {}
_last_suggested_regime_v2: dict = {}
_last_detection_source: dict = {}
_last_detection_timestamp_epoch: dict = {}
_last_effective_strategy: dict = {}
_last_effective_route: dict = {}
_last_route_eval_ts: dict = {}
_last_regime_eval_ts: dict = {}
_last_auto_fallback_reason: dict = {}
_last_fallback_reason: dict = {}
_last_ready_for_non_mr_route: dict = {}
_last_non_mr_ready_reason: dict = {}
_last_route_readiness_state: dict = {}
_last_route_timestamp_age_seconds: dict = {}
_last_route_timestamp_fresh: dict = {}
_last_shadow_continuity_state: dict = {}
_last_shadow_age_seconds: dict = {}
_last_failed_gates: dict = {}
_last_decision_diagnostics: dict = {}
_last_buy_block_reason: dict = {}
_last_buy_block_route: dict = {}
_buy_block_counts_by_symbol: dict = {}
_buy_block_counts_by_symbol_route: dict = {}
_entry_route: dict = {}
_entry_regime: dict = {}
_exit_policy: dict = {}
_entry_confidence: dict = {}
_entry_timestamp: dict = {}
_entry_route_eval_ts: dict = {}
_entry_regime_eval_ts: dict = {}
_pending_entry_contract: dict = {}
_shadow_regime_state: dict = {}
_synced = False
_last_paper_state_mtime = None
_metrics_dirty = False
_last_metrics_flush_at = 0.0

EXIT_POLICY_MR = "mr_exit"
EXIT_POLICY_TREND = "trend_exit"
EXIT_POLICY_BREAKOUT = "breakout_exit"
EXIT_POLICY_SCALPER = "scalper_exit"

METRICS_FLUSH_INTERVAL_SECONDS = 5.0
SCORE_EPSILON = 0.01
VOLATILITY_EPSILON = 1e-6
DEFAULT_AUTO_MAX_ROUTE_AGE_SECONDS = 15 * 60

ROUTE_METADATA_MAPS = {
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
    "last_ready_for_non_mr_route": _last_ready_for_non_mr_route,
    "last_non_mr_ready_reason": _last_non_mr_ready_reason,
    "last_route_readiness_state": _last_route_readiness_state,
    "last_route_timestamp_age_seconds": _last_route_timestamp_age_seconds,
    "last_route_timestamp_fresh": _last_route_timestamp_fresh,
    "last_shadow_continuity_state": _last_shadow_continuity_state,
    "last_shadow_age_seconds": _last_shadow_age_seconds,
    "last_failed_gates": _last_failed_gates,
    "last_decision_diagnostics": _last_decision_diagnostics,
}
