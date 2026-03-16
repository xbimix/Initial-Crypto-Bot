import time
from pathlib import Path

from strategy.breakout_momentum import evaluate_breakout_momentum_entry
from strategy.regime_engine import normalize_shadow_state, update_regime_shadow_state
from strategy.regime_router import resolve_entry_route
from strategy.regime import detect_regime
from strategy.scoring import score_indicators
from strategy.trend_pullback import evaluate_trend_pullback_entry
from utils.logger import setup_logger
from utils.state_io import read_json_file, write_json_file

try:
    from analysis.data_analysis import calculate_support_resistance
except ModuleNotFoundError:
    from crypto_bot.analysis.data_analysis import calculate_support_resistance

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
_last_effective_strategy = {}
_last_auto_fallback_reason = {}
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
    if not PAPER_STATE_FILE.exists():
        """
        On startup, align strategy state with PaperBroker positions.
        """
        return

    try:
        data = read_json_file(PAPER_STATE_FILE, default={})
        if not isinstance(data, dict):
            data = {}

        positions = data.get("positions", {})
        broker_symbols = set(positions)
        state_changed = False

        # Paper broker state is the source of truth for which positions are open.
        for symbol in list(_entry_price.keys()):
            if symbol not in broker_symbols:
                _entry_price.pop(symbol, None)
                _entry_time.pop(symbol, None)
                _profit_lock.pop(symbol, None)
                _peak_pnl.pop(symbol, None)
                _last_momentum.pop(symbol, None)
                _last_signal.pop(symbol, None)
                state_changed = True
                logger.info(f"Strategy sync: removed stale state for {symbol}")

        for symbol in list(_entry_time.keys()):
            if symbol not in broker_symbols:
                _entry_time.pop(symbol, None)
                state_changed = True

        for symbol in list(_profit_lock.keys()):
            if symbol not in broker_symbols:
                _profit_lock.pop(symbol, None)
                state_changed = True

        for symbol in list(_peak_pnl.keys()):
            if symbol not in broker_symbols:
                _peak_pnl.pop(symbol, None)
                state_changed = True

        for symbol in list(_last_momentum.keys()):
            if symbol not in broker_symbols:
                _last_momentum.pop(symbol, None)
                state_changed = True

        for symbol in list(_last_signal.keys()):
            if symbol not in broker_symbols:
                _last_signal.pop(symbol, None)
                state_changed = True

        for mapping in (
            _last_regime,
            _last_score,
            _last_volatility,
            _last_configured_regime,
            _last_detected_regime,
            _last_detected_regime_confidence,
            _last_detected_regime_confidence_label,
            _last_effective_strategy,
            _last_auto_fallback_reason,
        ):
            for symbol in list(mapping.keys()):
                if symbol in broker_symbols:
                    continue
                mapping.pop(symbol, None)
                state_changed = True

        for symbol, pos in positions.items():
            entry_price = pos.get("price")
            entry_time = _parse_numeric(pos.get("entry_time"), fallback=None)
            if entry_time is None:
                entry_time = time.time()
            if symbol not in _entry_price:
                _entry_price[symbol] = entry_price
                _entry_time[symbol] = entry_time
                _profit_lock[symbol] = None
                _last_signal[symbol] = "BUY"
                state_changed = True
                logger.info(f"Strategy sync: restored {symbol} @ {entry_price}")
            elif _entry_price.get(symbol) != entry_price:
                _entry_price[symbol] = entry_price
                state_changed = True
                logger.info(f"Strategy sync: reconciled {symbol} entry to {entry_price}")
            if _entry_time.get(symbol) != entry_time:
                _entry_time[symbol] = entry_time
                state_changed = True

            if symbol not in _profit_lock:
                _profit_lock[symbol] = None
                state_changed = True
            if symbol not in _peak_pnl:
                _peak_pnl[symbol] = 0.0
                state_changed = True
            if _last_signal.get(symbol) != "BUY":
                _last_signal[symbol] = "BUY"
                state_changed = True

        if state_changed:
            _save_strategy_state()

    except Exception as e:
        logger.exception(f"Strategy state sync failed: {e}")


def _paper_state_mtime():
    try:
        return PAPER_STATE_FILE.stat().st_mtime
    except OSError:
        return None


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
    entry_route = resolve_entry_route(
        cfg=cfg,
        symbol=symbol,
        snapshot=snapshot,
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
    effective = route.get("effective_strategy")
    fallback_reason = route.get("auto_fallback_reason")
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

    if isinstance(effective, str) and effective:
        if _last_effective_strategy.get(symbol) != effective:
            _last_effective_strategy[symbol] = effective
            changed = True
    else:
        if symbol in _last_effective_strategy:
            _last_effective_strategy.pop(symbol, None)
            changed = True

    if isinstance(fallback_reason, str) and fallback_reason:
        if _last_auto_fallback_reason.get(symbol) != fallback_reason:
            _last_auto_fallback_reason[symbol] = fallback_reason
            changed = True
    else:
        if symbol in _last_auto_fallback_reason:
            _last_auto_fallback_reason.pop(symbol, None)
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
    if entry is None:
        return None

    pnl_pct = (price - entry) / entry
    current_lock = _profit_lock.get(symbol)
    saved_peak = _peak_pnl.get(symbol)
    peak_pnl = pnl_pct if saved_peak is None else max(saved_peak, pnl_pct)
    state_changed = False

    if pnl_pct < first_activation:
        reset_peak = max(pnl_pct, 0.0) if reset_below_activation else peak_pnl
        if _peak_pnl.get(symbol) != reset_peak:
            _peak_pnl[symbol] = reset_peak
            state_changed = True
        if reset_below_activation and current_lock is not None:
            _profit_lock[symbol] = None
            state_changed = True
        if state_changed:
            _save_strategy_state()
        return _decision(symbol, "HOLD", price, momentum, "waiting_for_first_lock")

    if _peak_pnl.get(symbol) != peak_pnl:
        _peak_pnl[symbol] = peak_pnl
        state_changed = True

    if current_lock is None:
        current_lock = initial_lock

    for trigger, lock in profit_levels:
        if pnl_pct >= trigger:
            current_lock = max(current_lock, lock)

    if peak_pnl >= trailing_activation:
        current_lock = max(current_lock, peak_pnl - trailing_gap)

    previous_lock = _profit_lock.get(symbol)
    if previous_lock != current_lock:
        _profit_lock[symbol] = current_lock
        state_changed = True

    if state_changed:
        _save_strategy_state()

    logger.info(
        f"{symbol} PNL={pnl_pct:.4f} | lock={current_lock:.4f} | "
        f"lock_price={(entry * (1 + current_lock)):.2f}"
    )

    if pnl_pct <= current_lock:
        if symbol not in _entry_price:
            return _decision(symbol, "HOLD", price, momentum, "desync_protection")

        return _decision(
            symbol,
            "SELL",
            price,
            momentum,
            f"profit_lock_exit_{int(current_lock*100)}pct",
        )

    if z_score is not None and current_lock == 0.01 and z_score < max_negative_z_score:
        return _decision(symbol, "SELL", price, momentum, "structural_break_exit")

    return _decision(symbol, "HOLD", price, momentum, "in_position")


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
    if entry is None:
        return None

    now = time.time()
    if entry_ts is None:
        entry_ts = _entry_time.get(symbol)
    entry_ts = _parse_numeric(entry_ts, fallback=None)
    if entry_ts is None:
        entry_ts = now
        _entry_time[symbol] = entry_ts

    atr_value = _parse_numeric(atr, fallback=0.0) or 0.0
    min_move_pct = max(
        _parse_numeric(scalper_cfg.get("min_move_pct"), fallback=0.0015) or 0.0015,
        0.0,
    )
    take_profit_pct = max(
        atr_value * max(scalper_cfg.get("take_profit_atr_mult", 0.6), 0.0),
        min_move_pct,
    )
    stop_loss_pct = max(
        atr_value * max(scalper_cfg.get("stop_loss_atr_mult", 0.35), 0.0),
        min_move_pct * 0.75,
    )
    max_hold_seconds = max(int(scalper_cfg.get("max_hold_seconds", 180)), 1)
    exit_z_score = _parse_numeric(
        scalper_cfg.get("exit_z_score"),
        fallback=0.8,
    )

    pnl_pct = (price - entry) / entry
    _peak_pnl[symbol] = max(_peak_pnl.get(symbol, pnl_pct), pnl_pct)

    if pnl_pct >= take_profit_pct:
        return _decision(symbol, "SELL", price, momentum, "scalper_take_profit")

    if pnl_pct <= -stop_loss_pct:
        return _decision(symbol, "SELL", price, momentum, "scalper_stop_loss")

    if (
        z_score is not None
        and exit_z_score is not None
        and z_score >= exit_z_score
        and pnl_pct > 0
    ):
        return _decision(symbol, "SELL", price, momentum, "scalper_vwap_exit")

    if (now - entry_ts) >= max_hold_seconds:
        return _decision(symbol, "SELL", price, momentum, "scalper_time_stop")

    return _decision(symbol, "HOLD", price, momentum, "scalper_in_position")


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

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    state = {
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
        "last_effective_strategy": _last_effective_strategy,
        "last_auto_fallback_reason": _last_auto_fallback_reason,
        "shadow_regime_state": _shadow_regime_state,
    }

    write_json_file(STRATEGY_STATE_FILE, state)
    _metrics_dirty = False
    _last_metrics_flush_at = time.time()


def _load_strategy_state():
    if not STRATEGY_STATE_FILE.exists():
        return

    try:
        state = read_json_file(STRATEGY_STATE_FILE, default={})
        if not isinstance(state, dict):
            state = {}

        _entry_price.update(state.get("entry_price", {}))
        _entry_time.update(state.get("entry_time", {}))
        _profit_lock.update(state.get("profit_lock", {}))
        _peak_pnl.update(state.get("peak_pnl", {}))
        _last_signal.update(state.get("last_signal", {}))
        _last_momentum.update(state.get("last_momentum", {}))
        _last_regime.update(state.get("last_regime", {}))
        _last_score.update(state.get("last_score", {}))
        _last_volatility.update(state.get("last_volatility", {}))
        _last_configured_regime.update(state.get("last_configured_regime", {}))
        _last_detected_regime.update(state.get("last_detected_regime", {}))
        _last_detected_regime_confidence.update(state.get("last_detected_regime_confidence", {}))
        _last_detected_regime_confidence_label.update(state.get("last_detected_regime_confidence_label", {}))
        _last_effective_strategy.update(state.get("last_effective_strategy", {}))
        _last_auto_fallback_reason.update(state.get("last_auto_fallback_reason", {}))
        _shadow_regime_state.update(
            normalize_shadow_state(state.get("shadow_regime_state", {}))
        )

        logger.info("Strategy state restored")

    except Exception as e:
        logger.error(f"Failed to load strategy state: {e}")


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
    _last_effective_strategy.pop(symbol, None)
    _last_auto_fallback_reason.pop(symbol, None)


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
    if symbol in _last_effective_strategy:
        payload["effective_strategy"] = _last_effective_strategy[symbol]
    if symbol in _last_auto_fallback_reason:
        payload["auto_fallback_reason"] = _last_auto_fallback_reason[symbol]
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
    regime = detect_regime(snapshot, regime_cfg)
    volatility = _parse_numeric(atr, fallback=None)

    range_pos = None
    if high_24h > low_24h:
        range_pos = (price - low_24h) / (high_24h - low_24h)
        range_pos = max(0.0, min(1.0, range_pos))

    rsi = _parse_numeric(snapshot.get("rsi"), fallback=None)
    if rsi is None:
        if range_pos is not None:
            rsi = range_pos * 100.0
        elif z_score is not None:
            rsi = max(0.0, min(100.0, 50.0 + (z_score * 10.0)))
        else:
            rsi = 50.0

    structure = 0.0
    recent_prices = snapshot.get("recent_prices")
    if isinstance(recent_prices, list):
        valid_prices = []
        for raw in recent_prices:
            value = _parse_numeric(raw, fallback=None)
            if value is None or value <= 0:
                continue
            valid_prices.append(value)

        if len(valid_prices) >= 5:
            try:
                support, resistance = calculate_support_resistance(
                    valid_prices,
                    window=min(14, len(valid_prices)),
                )
                if price <= support * 1.01:
                    structure = 1.0
                elif price >= resistance * 0.995:
                    structure = -1.0
            except Exception:
                structure = 0.0

    indicators = {
        "rsi": rsi,
        "momentum": _parse_numeric(momentum, fallback=0.0),
        "structure": structure,
    }

    score = score_indicators(
        regime=regime,
        indicators=indicators,
        range_pos=range_pos if range_pos is not None else 0.0,
    )

    return regime, float(score), range_pos, volatility


def _normalize_symbol(value):
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def _normalize_strategy_name(value):
    raw = str(value or "").strip().lower()
    if raw in {"volatility_scalper", "vol_scalper", "scalper"}:
        return "volatility_scalper"
    return "mean_reversion"


def _resolve_scalper_config(cfg):
    raw = cfg.get("volatility_scalper", {})
    if not isinstance(raw, dict):
        raw = {}

    symbols = set()
    raw_symbols = raw.get("symbols", [])
    if isinstance(raw_symbols, list):
        for item in raw_symbols:
            symbol = _normalize_symbol(item)
            if symbol:
                symbols.add(symbol)

    max_range_pos = _parse_numeric(raw.get("max_range_pos"), fallback=0.65)
    if max_range_pos is not None:
        max_range_pos = max(0.0, min(1.0, max_range_pos))

    return {
        "enabled": raw.get("enabled", True) is not False,
        "symbols": symbols,
        "min_atr": max(_parse_numeric(raw.get("min_atr"), fallback=0.008) or 0.008, 0.0),
        "min_trades": max(int(_parse_numeric(raw.get("min_trades"), fallback=6) or 6), 1),
        "max_spread_bps": max(
            _parse_numeric(raw.get("max_spread_bps"), fallback=120.0) or 120.0,
            0.0,
        ),
        "min_momentum": _parse_numeric(raw.get("min_momentum"), fallback=0.2),
        "entry_z_score_max": _parse_numeric(raw.get("entry_z_score_max"), fallback=-0.1),
        "exit_z_score": _parse_numeric(raw.get("exit_z_score"), fallback=0.8),
        "take_profit_atr_mult": max(
            _parse_numeric(raw.get("take_profit_atr_mult"), fallback=0.6) or 0.6,
            0.0,
        ),
        "stop_loss_atr_mult": max(
            _parse_numeric(raw.get("stop_loss_atr_mult"), fallback=0.35) or 0.35,
            0.0,
        ),
        "max_hold_seconds": max(
            int(_parse_numeric(raw.get("max_hold_seconds"), fallback=180) or 180),
            1,
        ),
        "min_move_pct": max(
            _parse_numeric(raw.get("min_move_pct"), fallback=0.0015) or 0.0015,
            0.0,
        ),
        "min_score_to_buy": max(
            _parse_numeric(raw.get("min_score_to_buy"), fallback=55.0) or 55.0,
            0.0,
        ),
        "max_range_pos": max_range_pos,
    }


def _strategy_for_symbol(cfg, symbol, scalper_cfg):
    symbol_key = _normalize_symbol(symbol)
    if not symbol_key:
        return "mean_reversion"

    symbol_strategies = cfg.get("symbol_strategies", {})
    if isinstance(symbol_strategies, dict):
        for raw_symbol, raw_strategy in symbol_strategies.items():
            if _normalize_symbol(raw_symbol) != symbol_key:
                continue
            return _normalize_strategy_name(raw_strategy)

    strategy_overrides = cfg.get("strategy_overrides", {})
    if isinstance(strategy_overrides, dict):
        for raw_symbol, override in strategy_overrides.items():
            if _normalize_symbol(raw_symbol) != symbol_key:
                continue

            mode = override
            if isinstance(override, dict):
                mode = override.get("strategy", override.get("mode"))
            return _normalize_strategy_name(mode)

    if scalper_cfg.get("enabled") and symbol_key in scalper_cfg.get("symbols", set()):
        return "volatility_scalper"

    return "mean_reversion"


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
    regime = detect_regime(snapshot, regime_cfg)
    volatility = _parse_numeric(atr, fallback=None)

    range_pos = None
    if high_24h > low_24h:
        range_pos = (price - low_24h) / (high_24h - low_24h)
        range_pos = max(0.0, min(1.0, range_pos))

    score = 0.0
    min_atr = scalper_cfg.get("min_atr", 0.008)
    if volatility is not None:
        if volatility >= min_atr:
            score += 45
            score += min((volatility - min_atr) / max(min_atr, 1e-9), 1.0) * 20.0
        else:
            score += max(volatility / max(min_atr, 1e-9), 0.0) * 35.0

    momentum_value = _parse_numeric(momentum, fallback=0.0) or 0.0
    if momentum_value > 0:
        score += min(momentum_value / 2.0, 1.0) * 20.0

    spread_bps = _parse_numeric(snapshot.get("spread_bps"), fallback=None)
    max_spread_bps = max(scalper_cfg.get("max_spread_bps", 120.0), 1e-9)
    if spread_bps is not None:
        if spread_bps <= max_spread_bps:
            score += 15.0
        else:
            penalty = min(((spread_bps - max_spread_bps) / max_spread_bps) * 30.0, 40.0)
            score -= penalty

    entry_z_score_max = scalper_cfg.get("entry_z_score_max")
    if z_score is not None and entry_z_score_max is not None:
        if z_score <= entry_z_score_max:
            score += 15.0
        elif z_score >= 1.2:
            score -= 15.0

    if range_pos is not None:
        max_range_pos = scalper_cfg.get("max_range_pos")
        if max_range_pos is not None and range_pos <= max_range_pos:
            score += 10.0
        elif range_pos > 0.8:
            score -= 10.0

    if regime in {"trend_down", "dump"}:
        score -= 10.0
    elif regime in {"trend_up", "accumulation", "spike"}:
        score += 5.0

    score = max(0.0, min(score, 100.0))
    return regime, float(score), range_pos, volatility


def _record_symbol_metrics(symbol, regime, score, volatility):
    global _metrics_dirty

    changed = False

    if _last_regime.get(symbol) != regime:
        _last_regime[symbol] = regime
        changed = True

    previous_score = _parse_numeric(_last_score.get(symbol), fallback=None)
    if previous_score is None or abs(previous_score - score) > SCORE_EPSILON:
        _last_score[symbol] = float(score)
        changed = True

    if volatility is None:
        if symbol in _last_volatility:
            _last_volatility.pop(symbol, None)
            changed = True
    else:
        previous_volatility = _parse_numeric(
            _last_volatility.get(symbol),
            fallback=None,
        )
        if (
            previous_volatility is None
            or abs(previous_volatility - volatility) > VOLATILITY_EPSILON
        ):
            _last_volatility[symbol] = float(volatility)
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
