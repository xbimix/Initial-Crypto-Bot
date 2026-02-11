from utils.logger import setup_logger

logger = setup_logger("strategy")

# -----------------------------
# Internal strategy state
# -----------------------------
_last_signal = {}
_last_sell_price = {}
_entry_price = {}
_profit_lock = {}
_last_momentum = {}


def evaluate_symbol(snapshot: dict, cfg: dict) -> dict:
    return generate_decision(snapshot, cfg)


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

    min_trades = cfg.get("min_trades", 3)

    prev_signal = _last_signal.get(symbol)
    last_sell = _last_sell_price.get(symbol)
    entry = _entry_price.get(symbol)
    prev_mom = _last_momentum.get(symbol)
    
    atr = snapshot.get("atr")

    min_atr = cfg.get("market_regime", {}).get("min_atr", 0.003)

    if atr is None or atr < min_atr:
     _last_signal[symbol] = "HOLD"
     return _decision(symbol, "HOLD", price, momentum, "atr_too_low")

    # --------------------------------------------------
    # SAFETY GUARDS
    # --------------------------------------------------
    if (
        trades < min_trades
        or high_24h <= low_24h
        or vwap is None
        or atr is None
        or atr <= 0
    ):
        _last_signal[symbol] = "HOLD"
        return _decision(symbol, "HOLD", price, momentum, "insufficient_data")
     

    

    # --------------------------------------------------
    # HARD PRICE LOCATION RULE (ABSOLUTE)
    # --------------------------------------------------
    range_width = high_24h - low_24h
    range_pos = (price - low_24h) / range_width

    if range_pos > 0.30:
        _last_signal[symbol] = "HOLD"
        return _decision(symbol, "HOLD", price, momentum, "price_above_30pct_range")

    if range_pos < 0.15:
        _last_signal[symbol] = "HOLD"
        return _decision(symbol, "HOLD", price, momentum, "price_below_15pct_range")

    # --------------------------------------------------
    # VOLATILITY STRETCH (MEAN REVERSION CORE)
    # --------------------------------------------------
    z_score = (price - vwap) / atr

    if z_score > -1.5:
        _last_signal[symbol] = "HOLD"
        return _decision(symbol, "HOLD", price, momentum, "insufficient_volatility_stretch")

    # --------------------------------------------------
    # MOMENTUM DECELERATION (NOT STRENGTH)
    # --------------------------------------------------
    if prev_mom is not None and momentum < prev_mom:
        _last_momentum[symbol] = momentum
        _last_signal[symbol] = "HOLD"
        return _decision(symbol, "HOLD", price, momentum, "momentum_still_falling")

    _last_momentum[symbol] = momentum

    # --------------------------------------------------
    # BUY LOGIC — BEAR MARKET ONLY
    # --------------------------------------------------
    if entry is None and prev_signal != "BUY":
        _entry_price[symbol] = price
        _profit_lock[symbol] = 0.0
        _last_signal[symbol] = "BUY"
         
        _log_decision(
            symbol, price, momentum_raw, momentum, atr,
            low_24h, high_24h,
            range_pos, 0.20, 0.30,
            prev_signal, last_sell,
            "BUY", "bear_market_mean_reversion_buy"
        )
         
        return _decision(symbol, "BUY", price, momentum, "bear_market_mean_reversion_buy")
   #-----------------------------------------------------------------------------------
# --------------------------------------------------
# SELL LOGIC — PROFIT LOCK LADDER (STABLE VERSION)
# --------------------------------------------------
    if entry is not None:

     pnl_pct = (price - entry) / entry
     current_lock = _profit_lock.get(symbol, None)

    # ---------------------------------------
    # 1️⃣ DO NOTHING until +2% is reached
    # ---------------------------------------
    if pnl_pct < 0.02:
        return _decision(symbol, "HOLD", price, momentum, "waiting_for_first_lock")

    # ---------------------------------------
    # 2️⃣ Initialize first lock at +1%
    # ---------------------------------------
    if current_lock is None:
        current_lock = 0.01

    # ---------------------------------------
    # 3️⃣ Progressive lock ladder
    # ---------------------------------------
    PROFIT_LOCKS = [
        (0.04, 0.03),
        (0.05, 0.04),
        (0.06, 0.05),
        (0.08, 0.06),
    ]

    for trigger, lock in PROFIT_LOCKS:
        if pnl_pct >= trigger:
            current_lock = max(current_lock, lock)

    _profit_lock[symbol] = current_lock

    # ---------------------------------------
    # 4️⃣ Exit only if price falls below locked level
    # ---------------------------------------
    if pnl_pct <= current_lock:
        _cleanup(symbol, price)
        return _decision(
            symbol,
            "SELL",
            price,
            momentum,
            f"profit_lock_exit_{int(current_lock*100)}pct"
        )

    # ---------------------------------------
    # 5️⃣ Structural break ONLY after profit
    # ---------------------------------------
    if pnl_pct >= 0.02 and z_score < -3.0:
        _cleanup(symbol, price)
        return _decision(
            symbol,
            "SELL",
            price,
            momentum,
            "structural_break_exit"
        )




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

    # --------------------------------------------------
    # FALLBACK
    # --------------------------------------------------
    _last_signal[symbol] = "HOLD"
    return _decision(symbol, "HOLD", price, momentum, "neutral")


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def _cleanup(symbol, price):
    _last_signal[symbol] = "SELL"
    _last_sell_price[symbol] = price
    _entry_price.pop(symbol, None)
    _profit_lock.pop(symbol, None)
    _last_momentum.pop(symbol, None)


def _log_decision(
    symbol, price, mom_raw, mom_norm, vol,
    low_24h, high_24h,
    range_pos, lower_band, upper_band,
    prev_signal, last_sell,
    action, reason
):
    logger.info(
        f"DECISION {symbol} | "
        f"price={price:.5f} | "
        f"mom_raw={mom_raw:.5f} | "
        f"mom_norm={mom_norm:.5f} | "
        f"vol={vol:.5f} | "
        f"24h_low={low_24h:.5f} | "
        f"24h_high={high_24h:.5f} | "
        f"range_pos={range_pos:.3f} | "
        f"bands={lower_band:.2f}-{upper_band:.2f} | "
        f"prev_signal={prev_signal} | "
        f"last_sell={last_sell} | "
        f"action={action} | "
        f"reason={reason}"
    )


def _decision(symbol, action, price, momentum, reason):
    logger.info(f"{symbol} → {action} | reason={reason}")
    return {
        "symbol": symbol,
        "action": action,
        "price": price,
        "momentum": momentum,
        "reason": reason,
    }

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

