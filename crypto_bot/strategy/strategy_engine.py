import time
from pathlib import Path

from strategy.diagnostics import (
    compute_buy_diagnostics as _compute_buy_diagnostics_impl,
    compute_scalper_diagnostics as _compute_scalper_diagnostics_impl,
    record_symbol_metrics as _record_symbol_metrics_impl,
)
from strategy.exits.breakout_exit import evaluate_breakout_exit
from strategy.exits.mr_exit import evaluate_mr_exit
from strategy.exits.trend_exit import evaluate_trend_exit
from strategy.route_quality import load_route_quality_report_cached
from strategy.regime_engine import normalize_shadow_state, update_regime_shadow_state
from strategy.regime_engine_v2 import evaluate_regime_unified
from strategy.regime_router import resolve_entry_route
from strategy.regime import detect_regime
from strategy.routes.breakout_momentum import evaluate_breakout_momentum_route_entry
from strategy.routes.mean_reversion import evaluate_mean_reversion_entry
from strategy.routes.trend_pullback import evaluate_trend_pullback_route_entry
from strategy.route_scoring.breakout_score import compute_breakout_score_bundle
from strategy.route_scoring.mr_score import compute_mr_score_bundle
from strategy.route_scoring.trend_score import compute_trend_score_bundle
from strategy.route_metadata import (
    cleanup_symbol as _cleanup_route_metadata_symbol,
    inject_payload as _inject_route_metadata_payload,
    record_route_metadata as _record_route_metadata_impl,
    state_map as _route_metadata_state_map,
)
from strategy.routing import (
    advisory_has_required_fields as _advisory_has_required_fields_impl,
    configured_regime_for_symbol as _configured_regime_for_symbol_impl,
    router_cfg as _router_cfg_impl,
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
_last_ready_for_non_mr_route = {}
_last_non_mr_ready_reason = {}
_last_route_readiness_state = {}
_last_route_timestamp_age_seconds = {}
_last_route_timestamp_fresh = {}
_last_shadow_continuity_state = {}
_last_shadow_age_seconds = {}
_last_failed_gates = {}
_last_buy_block_reason = {}
_last_buy_block_route = {}
_buy_block_counts_by_symbol = {}
_buy_block_counts_by_symbol_route = {}
_entry_route = {}
_entry_regime = {}
_exit_policy = {}
_entry_confidence = {}
_entry_timestamp = {}
_entry_route_eval_ts = {}
_entry_regime_eval_ts = {}
_pending_entry_contract = {}
_shadow_regime_state = {}
_synced = False
_last_paper_state_mtime = None
_metrics_dirty = False
_last_metrics_flush_at = 0.0

EXIT_POLICY_MR = "mr_exit"
EXIT_POLICY_TREND = "trend_exit"
EXIT_POLICY_BREAKOUT = "breakout_exit"
EXIT_POLICY_SCALPER = "scalper_exit"

_route_metadata_maps = {
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
}

METRICS_FLUSH_INTERVAL_SECONDS = 5.0
SCORE_EPSILON = 0.01
VOLATILITY_EPSILON = 1e-6
DEFAULT_AUTO_MAX_ROUTE_AGE_SECONDS = 15 * 60

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
            *_route_metadata_maps.values(),
        ),
        entry_route_state=_entry_route,
        entry_regime_state=_entry_regime,
        exit_policy_state=_exit_policy,
        entry_confidence_state=_entry_confidence,
        entry_timestamp_state=_entry_timestamp,
        entry_route_eval_ts_state=_entry_route_eval_ts,
        entry_regime_eval_ts_state=_entry_regime_eval_ts,
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


def _router_max_route_age_seconds(cfg: dict) -> float:
    router = _router_cfg_impl(cfg)
    raw = router.get("auto_max_route_age_seconds")
    value = _parse_numeric(raw, fallback=DEFAULT_AUTO_MAX_ROUTE_AGE_SECONDS)
    if value is None or value <= 0:
        return float(DEFAULT_AUTO_MAX_ROUTE_AGE_SECONDS)
    return max(float(value), 60.0)


def _advisory_has_required_fields(advisory: dict) -> bool:
    return _advisory_has_required_fields_impl(advisory)


def _normalize_strategy(value, fallback: str = "mean_reversion") -> str:
    raw = str(value or "").strip().lower()
    if raw in {"mean_reversion", "trend_pullback", "breakout_momentum", "observe_only", "volatility_scalper"}:
        return raw
    return fallback


def _safe_confidence_value(value):
    parsed = _parse_numeric(value, fallback=None)
    if parsed is None:
        return None
    if 0 <= parsed <= 1.0:
        parsed *= 100.0
    return max(0.0, min(parsed, 100.0))


def _exit_policy_for_route(route: str) -> str:
    normalized = _normalize_strategy(route, fallback="mean_reversion")
    if normalized == "trend_pullback":
        return EXIT_POLICY_TREND
    if normalized == "breakout_momentum":
        return EXIT_POLICY_BREAKOUT
    if normalized == "volatility_scalper":
        return EXIT_POLICY_SCALPER
    return EXIT_POLICY_MR


def _active_route_for_position(symbol: str, fallback_route: str) -> str:
    stored = _normalize_strategy(_entry_route.get(symbol), fallback="")
    if stored:
        return stored
    return _normalize_strategy(fallback_route, fallback="mean_reversion")


def _active_exit_policy_for_position(symbol: str, active_route: str) -> str:
    existing = str(_exit_policy.get(symbol) or "").strip().lower()
    if existing in {EXIT_POLICY_MR, EXIT_POLICY_TREND, EXIT_POLICY_BREAKOUT, EXIT_POLICY_SCALPER}:
        return existing
    return _exit_policy_for_route(active_route)


def stage_entry_contract(symbol: str, contract: dict | None):
    if not isinstance(contract, dict):
        _pending_entry_contract.pop(symbol, None)
        return
    _pending_entry_contract[symbol] = {
        "entry_route": contract.get("entry_route"),
        "entry_regime": contract.get("entry_regime"),
        "exit_policy": contract.get("exit_policy"),
        "entry_confidence": contract.get("entry_confidence"),
        "entry_timestamp": contract.get("entry_timestamp"),
        "route_eval_ts": contract.get("route_eval_ts"),
        "regime_eval_ts": contract.get("regime_eval_ts"),
    }


def clear_entry_contract(symbol: str):
    _pending_entry_contract.pop(symbol, None)


def _attach_entry_contract_candidate(
    *,
    decision: dict,
    active_strategy: str,
    route: dict,
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
    decision.setdefault("entry_confidence", _safe_confidence_value(route.get("detected_regime_confidence")))
    decision.setdefault("entry_timestamp", now_epoch)
    decision.setdefault("entry_route_eval_ts", _parse_numeric(route.get("route_eval_ts"), fallback=now_epoch) or now_epoch)
    decision.setdefault("entry_regime_eval_ts", _parse_numeric(route.get("regime_eval_ts"), fallback=now_epoch) or now_epoch)
    return decision


# ============================================================
# CORE STRATEGY
# ============================================================

def generate_decision(snapshot: dict, cfg: dict) -> dict:
    global _metrics_dirty

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

        force_shadow_refresh = _router_flag(cfg, "auto_use_current_cycle_shadow", False)
        if not force_shadow_refresh:
            symbol_key = str(symbol or "").strip().upper()
            shadow_row = _shadow_regime_state.get(symbol_key, {})
            last_update_ts = _parse_numeric(
                shadow_row.get("last_update_ts") if isinstance(shadow_row, dict) else None,
                fallback=0.0,
            ) or 0.0
            max_route_age_seconds = _router_max_route_age_seconds(cfg)
            if last_update_ts <= 0 or (route_eval_ts - last_update_ts) > max_route_age_seconds:
                force_shadow_refresh = True

        if force_shadow_refresh:
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
    route_strategy = _normalize_strategy(
        entry_route.get("effective_strategy", strategy_mode),
        fallback=_normalize_strategy(strategy_mode, fallback="mean_reversion"),
    )
    effective_strategy = route_strategy
    _record_route_metadata(symbol, entry_route)
    in_position = entry is not None
    active_exit_policy = _exit_policy_for_route(effective_strategy)
    if in_position:
        # Open positions keep their entry route + exit policy; do not remap each cycle.
        effective_strategy = _active_route_for_position(symbol, "mean_reversion")
        active_exit_policy = _active_exit_policy_for_position(symbol, effective_strategy)
        if _last_effective_strategy.get(symbol) != effective_strategy:
            _last_effective_strategy[symbol] = effective_strategy
            _metrics_dirty = True
        if _last_effective_route.get(symbol) != effective_strategy:
            _last_effective_route[symbol] = effective_strategy
            _metrics_dirty = True
        if _last_fallback_reason.get(symbol) != "open_position_exit_policy_locked":
            _last_fallback_reason[symbol] = "open_position_exit_policy_locked"
            _metrics_dirty = True
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
    elif effective_strategy == "trend_pullback":
        regime, score, range_pos, volatility = compute_trend_score_bundle(
            snapshot=snapshot,
            price=price,
            momentum=momentum,
            high_24h=high_24h,
            low_24h=low_24h,
            atr=atr,
        )
    elif effective_strategy == "breakout_momentum":
        regime, score, range_pos, volatility = compute_breakout_score_bundle(
            snapshot=snapshot,
            price=price,
            momentum=momentum,
            high_24h=high_24h,
            low_24h=low_24h,
            atr=atr,
        )
    else:
        regime, score, range_pos, volatility = compute_mr_score_bundle(
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
    _record_symbol_metrics(symbol, regime, score, volatility)
    if not shadow_updated_pre_route or regime != pre_route_candidate_regime:
        _record_shadow_regime_metrics(
            symbol=symbol,
            snapshot=snapshot,
            candidate_regime=regime,
            cfg=cfg,
        )
    _flush_metrics_state_if_due()

    if active_exit_policy == EXIT_POLICY_SCALPER:
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
    elif active_exit_policy == EXIT_POLICY_TREND:
        sell_signal = evaluate_trend_exit(
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
            profit_lock_state=_profit_lock,
            peak_pnl_state=_peak_pnl,
            entry_price_state=_entry_price,
            save_strategy_state=_save_strategy_state,
            decision=_decision,
            logger=logger,
        )
    elif active_exit_policy == EXIT_POLICY_BREAKOUT:
        sell_signal = evaluate_breakout_exit(
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
            profit_lock_state=_profit_lock,
            peak_pnl_state=_peak_pnl,
            entry_price_state=_entry_price,
            save_strategy_state=_save_strategy_state,
            decision=_decision,
            logger=logger,
        )
    else:
        sell_signal = evaluate_mr_exit(
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
            profit_lock_state=_profit_lock,
            peak_pnl_state=_peak_pnl,
            entry_price_state=_entry_price,
            save_strategy_state=_save_strategy_state,
            decision=_decision,
            logger=logger,
        )

    # SELL is always allowed to fire while in a position.
    if sell_signal is not None:
        return sell_signal

    if effective_strategy == "observe_only":
        return _decision(symbol, "HOLD", price, momentum, "observe_only_mode")

    if effective_strategy == "volatility_scalper":
        decision = _evaluate_scalper_buy(
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
        )
        return _attach_entry_contract_candidate(
            decision=decision,
            active_strategy=effective_strategy,
            route=entry_route,
        )

    if effective_strategy == "trend_pullback":
        decision = _evaluate_trend_pullback_buy(
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
        )
        return _attach_entry_contract_candidate(
            decision=decision,
            active_strategy=effective_strategy,
            route=entry_route,
        )

    if effective_strategy == "breakout_momentum":
        decision = _evaluate_breakout_momentum_buy(
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
        )
        return _attach_entry_contract_candidate(
            decision=decision,
            active_strategy=effective_strategy,
            route=entry_route,
        )

    decision = _evaluate_buy(
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
    )
    return _attach_entry_contract_candidate(
        decision=decision,
        active_strategy=effective_strategy,
        route=entry_route,
    )


def _record_route_metadata(symbol: str, route: dict):
    global _metrics_dirty
    if _record_route_metadata_impl(
        symbol=symbol,
        route=route,
        route_maps=_route_metadata_maps,
        parse_numeric=_parse_numeric,
    ):
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
    data_quality_ok = snapshot.get("data_quality_ok")
    if data_quality_ok is not True:
        reason = snapshot.get("data_quality_reason")
        if not isinstance(reason, str) or not reason.strip():
            reason = "data_quality_missing" if data_quality_ok is None else "data_quality_failed"
        return _decision(
            symbol,
            "HOLD",
            price,
            momentum,
            str(reason),
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
        last_momentum_state=_last_momentum,
        decision=_decision,
    )


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
            "entry_route": _entry_route,
            "entry_regime": _entry_regime,
            "exit_policy": _exit_policy,
            "entry_confidence": _entry_confidence,
            "entry_timestamp": _entry_timestamp,
            "entry_route_eval_ts": _entry_route_eval_ts,
            "entry_regime_eval_ts": _entry_regime_eval_ts,
            "profit_lock": _profit_lock,
            "peak_pnl": _peak_pnl,
            "last_signal": _last_signal,
            "last_momentum": _last_momentum,
            "last_regime": _last_regime,
            "last_score": _last_score,
            "last_volatility": _last_volatility,
            "last_buy_block_reason": _last_buy_block_reason,
            "last_buy_block_route": _last_buy_block_route,
            "buy_block_counts_by_symbol": _buy_block_counts_by_symbol,
            "buy_block_counts_by_symbol_route": _buy_block_counts_by_symbol_route,
            **_route_metadata_state_map(_route_metadata_maps),
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
            "entry_route": _entry_route,
            "entry_regime": _entry_regime,
            "exit_policy": _exit_policy,
            "entry_confidence": _entry_confidence,
            "entry_timestamp": _entry_timestamp,
            "entry_route_eval_ts": _entry_route_eval_ts,
            "entry_regime_eval_ts": _entry_regime_eval_ts,
            "profit_lock": _profit_lock,
            "peak_pnl": _peak_pnl,
            "last_signal": _last_signal,
            "last_momentum": _last_momentum,
            "last_regime": _last_regime,
            "last_score": _last_score,
            "last_volatility": _last_volatility,
            "last_buy_block_reason": _last_buy_block_reason,
            "last_buy_block_route": _last_buy_block_route,
            "buy_block_counts_by_symbol": _buy_block_counts_by_symbol,
            "buy_block_counts_by_symbol_route": _buy_block_counts_by_symbol_route,
            **_route_metadata_state_map(_route_metadata_maps),
        },
        shadow_regime_state=_shadow_regime_state,
        logger=logger,
    )


# ============================================================
# HELPERS
# ============================================================
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
    staged = _pending_entry_contract.pop(symbol, None)
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
        entry_route or _last_effective_route.get(symbol) or _last_effective_strategy.get(symbol),
        fallback="mean_reversion",
    )
    resolved_exit_policy = str(exit_policy or _exit_policy_for_route(resolved_route)).strip().lower()
    if resolved_exit_policy not in {EXIT_POLICY_MR, EXIT_POLICY_TREND, EXIT_POLICY_BREAKOUT, EXIT_POLICY_SCALPER}:
        resolved_exit_policy = _exit_policy_for_route(resolved_route)
    resolved_timestamp = _parse_numeric(entry_timestamp, fallback=now) or now
    resolved_route_eval_ts = _parse_numeric(route_eval_ts, fallback=resolved_timestamp) or resolved_timestamp
    resolved_regime_eval_ts = _parse_numeric(regime_eval_ts, fallback=resolved_timestamp) or resolved_timestamp
    resolved_confidence = _safe_confidence_value(entry_confidence)
    resolved_regime = str(
        entry_regime
        or _last_suggested_regime_v2.get(symbol)
        or _last_detected_regime.get(symbol)
        or "MIXED_OR_UNCLEAR"
    )

    _entry_price[symbol] = price
    _entry_time[symbol] = resolved_timestamp
    _entry_route[symbol] = resolved_route
    _entry_regime[symbol] = resolved_regime
    _exit_policy[symbol] = resolved_exit_policy
    _entry_confidence[symbol] = resolved_confidence
    _entry_timestamp[symbol] = resolved_timestamp
    _entry_route_eval_ts[symbol] = resolved_route_eval_ts
    _entry_regime_eval_ts[symbol] = resolved_regime_eval_ts
    _profit_lock[symbol] = None
    _peak_pnl[symbol] = 0.0
    _last_signal[symbol] = "BUY"
    _save_strategy_state()


def confirm_exit(symbol: str, price: float):
    _cleanup(symbol, price)
    _save_strategy_state()


def _cleanup(symbol, price):
    _last_sell_price[symbol] = price
    _pending_entry_contract.pop(symbol, None)
    _entry_price.pop(symbol, None)
    _entry_time.pop(symbol, None)
    _entry_route.pop(symbol, None)
    _entry_regime.pop(symbol, None)
    _exit_policy.pop(symbol, None)
    _entry_confidence.pop(symbol, None)
    _entry_timestamp.pop(symbol, None)
    _entry_route_eval_ts.pop(symbol, None)
    _entry_regime_eval_ts.pop(symbol, None)
    _profit_lock.pop(symbol, None)
    _peak_pnl.pop(symbol, None)
    _last_signal.pop(symbol, None)
    _last_momentum.pop(symbol, None)
    _last_regime.pop(symbol, None)
    _last_score.pop(symbol, None)
    _last_volatility.pop(symbol, None)
    _cleanup_route_metadata_symbol(symbol, _route_metadata_maps)


def _decision(symbol, action, price, momentum, reason):
    logger.info(f"{symbol} -> {action} | reason={reason}")
    _record_buy_block_gate(symbol=symbol, action=action, reason=reason)
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
    if symbol in _entry_route:
        payload["entry_route"] = _entry_route[symbol]
    if symbol in _entry_regime:
        payload["entry_regime"] = _entry_regime[symbol]
    if symbol in _exit_policy:
        payload["exit_policy"] = _exit_policy[symbol]
    if symbol in _entry_confidence:
        payload["entry_confidence"] = _entry_confidence[symbol]
    if symbol in _entry_timestamp:
        payload["entry_timestamp"] = _entry_timestamp[symbol]
    if symbol in _entry_route_eval_ts:
        payload["entry_route_eval_ts"] = _entry_route_eval_ts[symbol]
    if symbol in _entry_regime_eval_ts:
        payload["entry_regime_eval_ts"] = _entry_regime_eval_ts[symbol]
    if symbol in _last_buy_block_reason:
        payload["last_buy_block_reason"] = _last_buy_block_reason[symbol]
    if symbol in _last_buy_block_route:
        payload["last_buy_block_route"] = _last_buy_block_route[symbol]
    _inject_route_metadata_payload(symbol, payload, _route_metadata_maps)
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


def _record_buy_block_gate(*, symbol, action, reason):
    global _metrics_dirty

    if action == "BUY":
        return
    # Buy-block diagnostics are only for symbols without an open position.
    if symbol in _entry_price:
        return

    symbol_key = str(symbol or "").strip().upper()
    if not symbol_key:
        return

    reason_key = str(reason or "").strip().lower()
    if not reason_key:
        reason_key = "unknown"
    route_key = _normalize_strategy(
        _last_effective_route.get(symbol_key) or _last_effective_strategy.get(symbol_key),
        fallback="mean_reversion",
    )

    changed = False
    if _last_buy_block_reason.get(symbol_key) != reason_key:
        _last_buy_block_reason[symbol_key] = reason_key
        changed = True
    if _last_buy_block_route.get(symbol_key) != route_key:
        _last_buy_block_route[symbol_key] = route_key
        changed = True

    symbol_bucket = _buy_block_counts_by_symbol.get(symbol_key)
    if not isinstance(symbol_bucket, dict):
        symbol_bucket = {}
    symbol_bucket[reason_key] = int(symbol_bucket.get(reason_key, 0) or 0) + 1
    _buy_block_counts_by_symbol[symbol_key] = symbol_bucket
    changed = True

    symbol_route_bucket = _buy_block_counts_by_symbol_route.get(symbol_key)
    if not isinstance(symbol_route_bucket, dict):
        symbol_route_bucket = {}
    route_bucket = symbol_route_bucket.get(route_key)
    if not isinstance(route_bucket, dict):
        route_bucket = {}
    route_bucket[reason_key] = int(route_bucket.get(reason_key, 0) or 0) + 1
    symbol_route_bucket[route_key] = route_bucket
    _buy_block_counts_by_symbol_route[symbol_key] = symbol_route_bucket
    changed = True

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
