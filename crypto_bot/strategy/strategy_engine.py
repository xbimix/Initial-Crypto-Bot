from utils.logger import setup_logger
from strategy.regime import detect_regime
from pathlib import Path

from utils.state_io import read_json_file, write_json_file

logger = setup_logger("strategy")

# -----------------------------
# Internal strategy state
# -----------------------------
_last_signal = {}
_last_sell_price = {}
_entry_price = {}
_profit_lock = {}
_peak_pnl = {}
_last_momentum = {}
_synced = False
_last_paper_state_mtime = None

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
                _profit_lock.pop(symbol, None)
                _peak_pnl.pop(symbol, None)
                _last_momentum.pop(symbol, None)
                _last_signal.pop(symbol, None)
                state_changed = True
                logger.info(f"Strategy sync: removed stale state for {symbol}")

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

        for symbol, pos in positions.items():
            entry_price = pos.get("price")
            if symbol not in _entry_price:
                _entry_price[symbol] = entry_price
                _profit_lock[symbol] = None
                _last_signal[symbol] = "BUY"
                state_changed = True
                logger.info(f"Strategy sync: restored {symbol} @ {entry_price}")
            elif _entry_price.get(symbol) != entry_price:
                _entry_price[symbol] = entry_price
                state_changed = True
                logger.info(f"Strategy sync: reconciled {symbol} entry to {entry_price}")

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
    momentum_raw = snapshot["momentum_raw"]
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

    min_trades = cfg.get("min_trades", 3)
    regime_cfg = cfg.get("market_regime", {})
    volatility_cfg = cfg.get("volatility_filters", {})
    profit_cfg = cfg.get("profit_locks", {})
    min_atr = volatility_cfg.get(
        "min_atr",
        regime_cfg.get("min_atr", cfg.get("min_atr", 0.003)),
    )
    min_atr_pct = volatility_cfg.get("min_atr_pct", min_atr)
    effective_min_atr = max(min_atr, min_atr_pct)
    buy_zone_low, buy_zone_high = regime_cfg.get("preferred_buy_zone", [0.05, 0.30])
    min_z_score = regime_cfg.get("min_z_score", -1.5)
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
        if sell_signal["action"] == "SELL":
            return sell_signal
        return sell_signal

    return _evaluate_buy(
        snapshot=snapshot,
        cfg=cfg,
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
        regime_cfg=regime_cfg,
        blocked_regimes=blocked_regimes,
    )


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


def _evaluate_buy(
    snapshot,
    cfg,
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
    regime_cfg,
    blocked_regimes,
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

    # Regime is advisory for entries unless explicitly hard-blocked in config.
    regime = detect_regime(snapshot, regime_cfg)
    if regime in blocked_regimes:
        return _decision(symbol, "HOLD", price, momentum, f"regime_{regime}")

    range_width = high_24h - low_24h
    range_pos = (price - low_24h) / range_width

    if range_pos > buy_zone_high:
        return _decision(symbol, "HOLD", price, momentum, "price_above_buy_zone")

    if range_pos < buy_zone_low:
        return _decision(symbol, "HOLD", price, momentum, "price_below_buy_zone")

    if z_score > min_z_score:
        return _decision(symbol, "HOLD", price, momentum, "insufficient_volatility_stretch")

    if prev_mom is not None and momentum < prev_mom:
        _last_momentum[symbol] = momentum
        return _decision(symbol, "HOLD", price, momentum, "momentum_still_falling")

    _last_momentum[symbol] = momentum
    return _decision(symbol, "BUY", price, momentum, "bear_market_mean_reversion_buy")


# ============================================================
# PERSISTENCE
# ============================================================

def _save_strategy_state():
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    state = {
        "entry_price": _entry_price,
        "profit_lock": _profit_lock,
        "peak_pnl": _peak_pnl,
        "last_signal": _last_signal,
        "last_momentum": _last_momentum,
    }

    write_json_file(STRATEGY_STATE_FILE, state)


def _load_strategy_state():
    if not STRATEGY_STATE_FILE.exists():
        return

    try:
        state = read_json_file(STRATEGY_STATE_FILE, default={})
        if not isinstance(state, dict):
            state = {}

        _entry_price.update(state.get("entry_price", {}))
        _profit_lock.update(state.get("profit_lock", {}))
        _peak_pnl.update(state.get("peak_pnl", {}))
        _last_signal.update(state.get("last_signal", {}))
        _last_momentum.update(state.get("last_momentum", {}))

        logger.info("Strategy state restored")

    except Exception as e:
        logger.error(f"Failed to load strategy state: {e}")


# ============================================================
# HELPERS
# ============================================================
def confirm_entry(symbol: str, price: float):
    _entry_price[symbol] = price
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
    _profit_lock.pop(symbol, None)
    _peak_pnl.pop(symbol, None)
    _last_signal.pop(symbol, None)
    _last_momentum.pop(symbol, None)


def _decision(symbol, action, price, momentum, reason):
    logger.info(f"{symbol} → {action} | reason={reason}")
    return {
        "symbol": symbol,
        "action": action,
        "price": price,
        "momentum": momentum,
        "reason": reason,
    }


_load_strategy_state()
