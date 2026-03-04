from utils.logger import setup_logger
from strategy.regime import detect_regime
import os
import json

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

STATE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "state")
)
STRATEGY_STATE_FILE = os.path.join(STATE_DIR, "strategy_state.json")
PAPER_STATE_FILE = os.path.join(STATE_DIR, "paper_state.json")


# ============================================================
# STATE SYNC
# ============================================================

def _sync_with_broker_state():
    if not os.path.exists(PAPER_STATE_FILE):
        """
        On startup, align strategy state with PaperBroker positions.
        """
        return

    try:
        with open(PAPER_STATE_FILE, "r") as f:
            data = json.load(f)

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


def evaluate_symbol(snapshot: dict, cfg: dict) -> dict:
    global _synced
    if not _synced:
        _sync_with_broker_state()
        _synced = True
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
    os.makedirs(STATE_DIR, exist_ok=True)

    state = {
        "entry_price": _entry_price,
        "profit_lock": _profit_lock,
        "peak_pnl": _peak_pnl,
        "last_signal": _last_signal,
        "last_momentum": _last_momentum,
    }

    with open(STRATEGY_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _load_strategy_state():
    if not os.path.exists(STRATEGY_STATE_FILE):
        return

    try:
        with open(STRATEGY_STATE_FILE, "r") as f:
            state = json.load(f)

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



# from utils.logger import setup_logger
# import os
# import json

# logger = setup_logger("strategy")

# # -----------------------------
# # Internal strategy state
# # -----------------------------
# _last_signal = {}
# _last_sell_price = {}
# _entry_price = {}
# _profit_lock = {}
# _last_momentum = {}

# STATE_DIR = os.path.abspath(
#     os.path.join(os.path.dirname(__file__), "..", "state")
# )
# STRATEGY_STATE_FILE = os.path.join(STATE_DIR, "strategy_state.json")
# PAPER_STATE_FILE = os.path.join(STATE_DIR, "paper_state.json")

# def _sync_with_broker_state():
#     """
#     On startup, align strategy state with PaperBroker positions.
#     """
#     if not os.path.exists(PAPER_STATE_FILE):
#         return

#     try:
#         with open(PAPER_STATE_FILE, "r") as f:
#             data = json.load(f)

#         positions = data.get("positions", {})

#         for symbol, pos in positions.items():
#             if symbol not in _entry_price:
#                 _entry_price[symbol] = pos.get("price")
#                 _profit_lock[symbol] = None
#                 _last_signal[symbol] = "BUY"

#                 logger.info(
#                     f"Strategy sync: restored {symbol} entry @ {pos.get('price')}"
#                 )

#     except Exception as e:
#         logger.exception(f"Strategy state sync failed: {e}")

# def evaluate_symbol(snapshot: dict, cfg: dict) -> dict:
   
#     _sync_with_broker_state()
#     return generate_decision(snapshot, cfg)


# def generate_decision(snapshot: dict, cfg: dict) -> dict:
#     symbol = snapshot["symbol"]
#     price = snapshot["price"]

#     momentum = snapshot["momentum_norm"]
#     momentum_raw = snapshot["momentum_raw"]
#     trades = snapshot["trade_count"]

#     high_24h = snapshot["high_24h"]
#     low_24h = snapshot["low_24h"]

#     atr = snapshot["atr"]
#     vwap = snapshot.get("vwap")

#     min_trades = cfg.get("min_trades", 3)

#     prev_signal = _last_signal.get(symbol)
#     last_sell = _last_sell_price.get(symbol)
#     entry = _entry_price.get(symbol)
#     prev_mom = _last_momentum.get(symbol)
    
#     atr = snapshot.get("atr")

#     min_atr = cfg.get("market_regime", {}).get("min_atr", 0.003)

#     if atr is None or atr < min_atr:
#      _last_signal[symbol] = "HOLD"
#      return _decision(symbol, "HOLD", price, momentum, "atr_too_low")

#     # --------------------------------------------------
#     # SAFETY GUARDS
#     # --------------------------------------------------
#     if (
#         trades < min_trades
#         or high_24h <= low_24h
#         or vwap is None
#         or atr is None
#         or atr <= 0
#     ):
#         _last_signal[symbol] = "HOLD"
#         return _decision(symbol, "HOLD", price, momentum, "insufficient_data")
     
#     # --------------------------------------------------
#     # HARD PRICE LOCATION RULE (ABSOLUTE)
#     # --------------------------------------------------
#     range_width = high_24h - low_24h
#     range_pos = (price - low_24h) / range_width

#     if range_pos > 0.30:
#         _last_signal[symbol] = "HOLD"
#         return _decision(symbol, "HOLD", price, momentum, "price_above_30pct_range")

#     if range_pos < 0.15:
#         _last_signal[symbol] = "HOLD"
#         return _decision(symbol, "HOLD", price, momentum, "price_below_15pct_range")

#     # --------------------------------------------------
#     # VOLATILITY STRETCH (MEAN REVERSION CORE)
#     # --------------------------------------------------
#     z_score = (price - vwap) / atr

#     if z_score > -1.5:
#         _last_signal[symbol] = "HOLD"
#         return _decision(symbol, "HOLD", price, momentum, "insufficient_volatility_stretch")

#     # --------------------------------------------------
#     # MOMENTUM DECELERATION (NOT STRENGTH)
#     # --------------------------------------------------
#     if prev_mom is not None and momentum < prev_mom:
#         _last_momentum[symbol] = momentum
#         _last_signal[symbol] = "HOLD"
#         return _decision(symbol, "HOLD", price, momentum, "momentum_still_falling")

#     _last_momentum[symbol] = momentum

#     # --------------------------------------------------
#     # BUY LOGIC — BEAR MARKET ONLY
#     # --------------------------------------------------
#     if entry is None and prev_signal != "BUY":
#         _entry_price[symbol] = price
#         _profit_lock[symbol] = 0.0
#         _last_signal[symbol] = "BUY"
        
#         _save_strategy_state()
 
#         _log_decision(
#             symbol, price, momentum_raw, momentum, atr,
#             low_24h, high_24h,
#             range_pos, 0.20, 0.30,
#             prev_signal, last_sell,
#             "BUY", "bear_market_mean_reversion_buy"
#         )
         
#         return _decision(symbol, "BUY", price, momentum, "bear_market_mean_reversion_buy")
#    #-----------------------------------------------------------------------------------
#     # --------------------------------------------------
# # SELL LOGIC — PROFIT LOCK LADDER
# # --------------------------------------------------
#     if entry is not None:

#      pnl_pct = (price - entry) / entry
#      current_lock = _profit_lock.get(symbol, None)

#     # 1️⃣ Do nothing until +2%
#     if pnl_pct < 0.02:
#         return _decision(symbol, "HOLD", price, momentum, "waiting_for_first_lock")

#     # 2️⃣ Initialize first lock
#     if current_lock is None:
#         current_lock = 0.01

#     # 3️⃣ Progressive ladder
#     PROFIT_LOCKS = [
#         (0.04, 0.03),
#         (0.05, 0.04),
#         (0.06, 0.05),
#         (0.08, 0.06),
#     ]

#     for trigger, lock in PROFIT_LOCKS:
#         if pnl_pct >= trigger:
#             current_lock = max(current_lock, lock)

#     _profit_lock[symbol] = current_lock
#     _save_strategy_state()

#     logger.info(
#         f"{symbol} PNL={pnl_pct:.4f} | lock={current_lock:.4f} | "
#         f"lock_price={(entry * (1 + current_lock)):.2f}"
#     )

#     # 4️⃣ Exit on lock breach
#     if pnl_pct <= current_lock:
#         _cleanup(symbol, price)
#         _save_strategy_state()
#         return _decision(
#             symbol,
#             "SELL",
#             price,
#             momentum,
#             f"profit_lock_exit_{int(current_lock*100)}pct"
#         )

#     # 5️⃣ Structural break (after profit)
#     if pnl_pct >= 0.02 and z_score < -3.0:
#         _cleanup(symbol, price)
#         _save_strategy_state()
#         return _decision(
#             symbol,
#             "SELL",
#             price,
#             momentum,
#             "structural_break_exit"
#         )
    
#     # --------------------------------------------------
#     # FALLBACK
#     # --------------------------------------------------
#     _last_signal[symbol] = "HOLD"
#     return _decision(symbol, "HOLD", price, momentum, "neutral")


# # --------------------------------------------------
# # STRATEGY STATE PERSISTENCE
# # --------------------------------------------------

# def _save_strategy_state():
#     os.makedirs(STATE_DIR, exist_ok=True)

#     state = {
#         "entry_price": _entry_price,
#         "profit_lock": _profit_lock,
#         "last_signal": _last_signal,
#         "last_momentum": _last_momentum,
#     }

#     with open(STRATEGY_STATE_FILE, "w") as f:
#         json.dump(state, f, indent=2)


# def _load_strategy_state():
#     if not os.path.exists(STRATEGY_STATE_FILE):
#         return

#     try:
#         with open(STRATEGY_STATE_FILE, "r") as f:
#             state = json.load(f)

#         _entry_price.update(state.get("entry_price", {}))
#         _profit_lock.update(state.get("profit_lock", {}))
#         _last_signal.update(state.get("last_signal", {}))
#         _last_momentum.update(state.get("last_momentum", {}))

#         logger.info("Strategy state restored")

#     except Exception as e:
#         logger.error(f"Failed to load strategy state: {e}")


# # --------------------------------------------------
# # HELPERS
# # --------------------------------------------------

# def _cleanup(symbol, price):
#     _last_signal[symbol] = "SELL"
#     _last_sell_price[symbol] = price
#     _entry_price.pop(symbol, None)
#     _profit_lock.pop(symbol, None)
#     _last_momentum.pop(symbol, None)



# def _log_decision(
#     symbol, price, mom_raw, mom_norm, vol,
#     low_24h, high_24h,
#     range_pos, lower_band, upper_band,
#     prev_signal, last_sell,
#     action, reason
# ):
#     logger.info(
#         f"DECISION {symbol} | "
#         f"price={price:.5f} | "
#         f"mom_raw={mom_raw:.5f} | "
#         f"mom_norm={mom_norm:.5f} | "
#         f"vol={vol:.5f} | "
#         f"24h_low={low_24h:.5f} | "
#         f"24h_high={high_24h:.5f} | "
#         f"range_pos={range_pos:.3f} | "
#         f"bands={lower_band:.2f}-{upper_band:.2f} | "
#         f"prev_signal={prev_signal} | "
#         f"last_sell={last_sell} | "
#         f"action={action} | "
#         f"reason={reason}"
#     )


# def _decision(symbol, action, price, momentum, reason):
#     logger.info(f"{symbol} → {action} | reason={reason}")
#     return {
#         "symbol": symbol,
#         "action": action,
#         "price": price,
#         "momentum": momentum,
#         "reason": reason,
#     }
# _load_strategy_state()





    # # --------------------------------------------------
    # # SELL LOGIC — PROFIT LOCK LADDER
    # # --------------------------------------------------
    # if entry is not None:
    #     pnl_pct = (price - entry) / entry
    #     current_lock = _profit_lock.get(symbol, 0.0)

    #     PROFIT_LOCKS = [
    #         (0.02, 0.01),
    #         (0.04, 0.03),
    #         (0.05, 0.04),
    #         (0.06, 0.05),
    #         (0.08, 0.06),
    #     ]

    #     for trigger, lock in PROFIT_LOCKS:
    #         if pnl_pct >= trigger:
    #             current_lock = max(current_lock, lock)

    #     _profit_lock[symbol] = current_lock

    #     if pnl_pct <= current_lock:
    #         _cleanup(symbol, price)
    #         return _decision(
    #             symbol,
    #             "SELL",
    #             price,
    #             momentum,
    #             f"profit_lock_exit_{int(current_lock*100)}pct"
    #         )

    #     if z_score < -3.0:
    #         _cleanup(symbol, price)
    #         return _decision(symbol, "SELL", price, momentum, "structural_break_exit")




# ✅ 2) STRATEGY — Fully Config-Driven Version
# 📁 strategy/strategy_engine.py

# This replaces your entire file.

# It uses:

# buy zone from config

# z-score from config

# profit ladder from config

# volatility filters from config

# no hardcoded numbers

# from utils.logger import setup_logger

# logger = setup_logger("strategy")

# _last_signal = {}
# _last_sell_price = {}
# _entry_price = {}
# _profit_lock = {}
# _last_momentum = {}


# def evaluate_symbol(snapshot: dict, cfg: dict) -> dict:
#     return generate_decision(snapshot, cfg)


# def generate_decision(snapshot: dict, cfg: dict) -> dict:
#     symbol = snapshot["symbol"]
#     price = snapshot["price"]

#     momentum = snapshot["momentum_norm"]
#     momentum_raw = snapshot["momentum_raw"]
#     trades = snapshot["trade_count"]

#     high_24h = snapshot["high_24h"]
#     low_24h = snapshot["low_24h"]

#     atr = snapshot.get("atr")
#     vwap = snapshot.get("vwap")

#     # --------------------------------------------------
#     # CONFIG EXTRACTION
#     # --------------------------------------------------

#     min_trades = cfg.get("min_trades", 3)

#     regime_cfg = cfg.get("market_regime", {})
#     buy_zone_low, buy_zone_high = regime_cfg.get("preferred_buy_zone", [0.15, 0.30])
#     min_z_score = regime_cfg.get("min_z_score", -1.5)

#     vol_cfg = cfg.get("volatility_filters", {})
#     min_atr = vol_cfg.get("min_atr", 0.001)
#     min_atr_pct = vol_cfg.get("min_atr_pct", 0.0005)

#     profit_cfg = cfg.get("profit_locks", {})
#     profit_levels = profit_cfg.get("levels", [0.02, 0.04, 0.06, 0.08])
#     floor_after_first = profit_cfg.get("floor_after_first", -0.05)
#     max_negative_z = profit_cfg.get("max_negative_z_score", -3.0)

#     prev_signal = _last_signal.get(symbol)
#     last_sell = _last_sell_price.get(symbol)
#     entry = _entry_price.get(symbol)
#     prev_mom = _last_momentum.get(symbol)

#     # --------------------------------------------------
#     # SAFETY GUARDS
#     # --------------------------------------------------

#     if (
#         trades < min_trades
#         or high_24h <= low_24h
#         or vwap is None
#         or atr is None
#         or atr <= 0
#     ):
#         _last_signal[symbol] = "HOLD"
#         return _decision(symbol, "HOLD", price, momentum, "insufficient_data")

#     # --------------------------------------------------
#     # VOLATILITY FILTER
#     # --------------------------------------------------

#     atr_pct = atr / price if price > 0 else 0

#     if atr < min_atr:
#         return _decision(symbol, "HOLD", price, momentum, "atr_below_floor")

#     if atr_pct < min_atr_pct:
#         return _decision(symbol, "HOLD", price, momentum, "effective_volatility_too_low")

#     # --------------------------------------------------
#     # PRICE LOCATION FILTER
#     # --------------------------------------------------

#     range_width = high_24h - low_24h
#     range_pos = (price - low_24h) / range_width

#     if range_pos < buy_zone_low:
#         return _decision(symbol, "HOLD", price, momentum, "below_buy_zone")

#     if range_pos > buy_zone_high:
#         return _decision(symbol, "HOLD", price, momentum, "above_buy_zone")

#     # --------------------------------------------------
#     # VOLATILITY STRETCH
#     # --------------------------------------------------

#     z_score = (price - vwap) / atr

#     if z_score > min_z_score:
#         return _decision(symbol, "HOLD", price, momentum, "no_volatility_stretch")

#     # --------------------------------------------------
#     # MOMENTUM DECELERATION
#     # --------------------------------------------------

#     if prev_mom is not None and momentum < prev_mom:
#         _last_momentum[symbol] = momentum
#         return _decision(symbol, "HOLD", price, momentum, "momentum_still_falling")

#     _last_momentum[symbol] = momentum

#     # --------------------------------------------------
#     # BUY LOGIC
#     # --------------------------------------------------

#     if entry is None:
#         _entry_price[symbol] = price
#         _profit_lock[symbol] = floor_after_first
#         _last_signal[symbol] = "BUY"

#         return _decision(symbol, "BUY", price, momentum, "bear_market_mean_reversion_buy")

#     # --------------------------------------------------
#     # SELL LOGIC — CONFIG DRIVEN
#     # --------------------------------------------------

#     pnl_pct = (price - entry) / entry
#     current_lock = _profit_lock.get(symbol, floor_after_first)

#     # Build dynamic ladder
#     dynamic_ladder = []
#     previous_level = floor_after_first

#     for lvl in profit_levels:
#         dynamic_ladder.append((lvl, previous_level))
#         previous_level = lvl

#     for trigger, lock in dynamic_ladder:
#         if pnl_pct >= trigger:
#             current_lock = max(current_lock, lock)

#     _profit_lock[symbol] = current_lock

#     if pnl_pct <= current_lock:
#         _cleanup(symbol, price)
#         return _decision(symbol, "SELL", price, momentum, f"profit_lock_exit")

#     # Structural break protection
#     if z_score < max_negative_z and pnl_pct > 0:
#         _cleanup(symbol, price)
#         return _decision(symbol, "SELL", price, momentum, "structural_break_exit")

#     return _decision(symbol, "HOLD", price, momentum, "neutral")


# def _cleanup(symbol, price):
#     _last_signal[symbol] = "SELL"
#     _last_sell_price[symbol] = price
#     _entry_price.pop(symbol, None)
#     _profit_lock.pop(symbol, None)
#     _last_momentum.pop(symbol, None)


# def _decision(symbol, action, price, momentum, reason):
#     logger.info(f"{symbol} → {action} | reason={reason}")
#     return {
#         "symbol": symbol,
#         "action": action,
#         "price": price,
#         "momentum": momentum,
#         "reason": reason,
#     }


