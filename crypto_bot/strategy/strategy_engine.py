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

    # --------------------------------------------------
    # SELL LOGIC — PROFIT LOCK LADDER
    # --------------------------------------------------
    if entry is not None:
        pnl_pct = (price - entry) / entry
        current_lock = _profit_lock.get(symbol, 0.0)

        PROFIT_LOCKS = [
            (0.02, -0.05),
            (0.04, 0.02),
            (0.06, 0.04),
            (0.08, 0.06),
        ]

        for trigger, lock in PROFIT_LOCKS:
            if pnl_pct >= trigger:
                current_lock = max(current_lock, lock)

        _profit_lock[symbol] = current_lock

        if pnl_pct <= current_lock:
            _cleanup(symbol, price)
            return _decision(
                symbol,
                "SELL",
                price,
                momentum,
                f"profit_lock_exit_{int(current_lock*100)}pct"
            )

        if z_score < -3.0:
            _cleanup(symbol, price)
            return _decision(symbol, "SELL", price, momentum, "structural_break_exit")

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



# from utils.logger import setup_logger

# logger = setup_logger("strategy")

# _last_signal = {}
# _last_sell_price = {}
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
#     volatility = snapshot["volatility"]

#     # REQUIRED for superior logic (already available in most pipelines)
#     vwap = snapshot.get("vwap")
#     atr = snapshot.get("atr")

#     min_trades = cfg.get("min_trades", 2)
#     entry_price = cfg.get("entry_price", {}).get(symbol)

#     prev_signal = _last_signal.get(symbol)
#     last_sell = _last_sell_price.get(symbol)
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
#     # HARDCORE PRICE LOCATION RULE (ABSOLUTE)
#     # --------------------------------------------------
#     range_width = high_24h - low_24h
#     range_pos = (price - low_24h) / range_width

#     if range_pos > 0.30:
#         _last_signal[symbol] = "HOLD"
#         return _decision(symbol, "HOLD", price, momentum, "price_above_30pct_range")

#     # --------------------------------------------------
#     # VOLATILITY EXCURSION (MEAN REVERSION CORE)
#     # --------------------------------------------------
#     z_score = (price - vwap) / atr

#     # Require deep stretch in bear market
#     if z_score > -1.5:
#         _last_signal[symbol] = "HOLD"
#         return _decision(symbol, "HOLD", price, momentum, "insufficient_volatility_stretch")

#     # --------------------------------------------------
#     # MOMENTUM DECELERATION (NOT STRENGTH)
#     # --------------------------------------------------
#     if prev_mom is not None and momentum < prev_mom:
#         _last_signal[symbol] = "HOLD"
#         return _decision(symbol, "HOLD", price, momentum, "momentum_still_falling")

#     _last_momentum[symbol] = momentum

#     # --------------------------------------------------
#     # BUY LOGIC — BEAR MARKET ONLY
#     # --------------------------------------------------
#     if entry_price is None and prev_signal != "BUY":
#         _last_signal[symbol] = "BUY"
#         _profit_lock[symbol] = None

#         _log_decision(
#             symbol, price, momentum_raw, momentum, volatility,
#             low_24h, high_24h,
#             range_pos, 0.20, 0.30,
#             prev_signal, last_sell,
#             "BUY", "bear_market_mean_reversion_buy"
#         )

#         return _decision(symbol, "BUY", price, momentum, "bear_market_mean_reversion_buy")

#     # --------------------------------------------------
#     # SELL LOGIC — PROFIT LOCK LADDER
#     # --------------------------------------------------
#     if entry_price is not None:
#         pnl_pct = (price - entry_price) / entry_price
#         current_lock = _profit_lock.get(symbol)

#         PROFIT_LOCKS = [
#             (0.02, 0.00),
#             (0.04, 0.02),
#             (0.06, 0.04),
#             (0.08, 0.06),
#         ]

#         for trigger, lock in PROFIT_LOCKS:
#             if pnl_pct >= trigger:
#                 if current_lock is None or lock > current_lock:
#                     _profit_lock[symbol] = lock
#                     current_lock = lock

#         # EXIT ON PROFIT LOCK BREACH
#         if current_lock is not None and pnl_pct <= current_lock:
#             _last_signal[symbol] = "SELL"
#             _last_sell_price[symbol] = price
#             _profit_lock.pop(symbol, None)

#             _log_decision(
#                 symbol, price, momentum_raw, momentum, volatility,
#                 low_24h, high_24h,
#                 range_pos, 0.20, 0.30,
#                 prev_signal, last_sell,
#                 "SELL", f"profit_lock_exit_{int(current_lock*100)}pct"
#             )

#             return _decision(
#                 symbol,
#                 "SELL",
#                 price,
#                 momentum,
#                 f"profit_lock_exit_{int(current_lock*100)}pct"
#             )

#         # HARD STRUCTURAL FAILURE
#         if z_score < -3.0:
#             _last_signal[symbol] = "SELL"
#             _last_sell_price[symbol] = price
#             _profit_lock.pop(symbol, None)

#             return _decision(symbol, "SELL", price, momentum, "structural_break_exit")

#     # --------------------------------------------------
#     # FALLBACK
#     # --------------------------------------------------
#     _last_signal[symbol] = "HOLD"
#     return _decision(symbol, "HOLD", price, momentum, "neutral")


# def _log_decision(
#     symbol, price, mom_raw, mom_norm, vol,
#     low_24h, high_24h,
#     range_pos, lower_band, upper_band,
#     prev_signal, last_sell,
#     action, reason
# ):
#     rp = f"{range_pos:.3f}" if range_pos is not None else "n/a"
#     bands = f"{lower_band:.2f}-{upper_band:.2f}"

#     logger.info(
#         f"DECISION {symbol} | "
#         f"price={price:.5f} | "
#         f"mom_raw={mom_raw:.5f} | "
#         f"mom_norm={mom_norm:.5f} | "
#         f"vol={vol:.5f} | "
#         f"24h_low={low_24h:.5f} | "
#         f"24h_high={high_24h:.5f} | "
#         f"range_pos={rp} | "
#         f"bands={bands} | "
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

