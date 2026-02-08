from utils.logger import setup_logger

logger = setup_logger("strategy")

_last_signal = {}
_last_sell_price = {}
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
    volatility = snapshot["volatility"]

    # REQUIRED for superior logic (already available in most pipelines)
    vwap = snapshot.get("vwap")
    atr = snapshot.get("atr")

    min_trades = cfg.get("min_trades", 3)
    entry_price = cfg.get("entry_price", {}).get(symbol)

    prev_signal = _last_signal.get(symbol)
    last_sell = _last_sell_price.get(symbol)
    prev_mom = _last_momentum.get(symbol)

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
    # HARDCORE PRICE LOCATION RULE (ABSOLUTE)
    # --------------------------------------------------
    range_width = high_24h - low_24h
    range_pos = (price - low_24h) / range_width

    if range_pos > 0.30:
        _last_signal[symbol] = "HOLD"
        return _decision(symbol, "HOLD", price, momentum, "price_above_30pct_range")

    # --------------------------------------------------
    # VOLATILITY EXCURSION (MEAN REVERSION CORE)
    # --------------------------------------------------
    z_score = (price - vwap) / atr

    # Require deep stretch in bear market
    if z_score > -1.5:
        _last_signal[symbol] = "HOLD"
        return _decision(symbol, "HOLD", price, momentum, "insufficient_volatility_stretch")

    # --------------------------------------------------
    # MOMENTUM DECELERATION (NOT STRENGTH)
    # --------------------------------------------------
    if prev_mom is not None and momentum < prev_mom:
        _last_signal[symbol] = "HOLD"
        return _decision(symbol, "HOLD", price, momentum, "momentum_still_falling")

    _last_momentum[symbol] = momentum

    # --------------------------------------------------
    # BUY LOGIC — BEAR MARKET ONLY
    # --------------------------------------------------
    if entry_price is None and prev_signal != "BUY":
        _last_signal[symbol] = "BUY"
        _profit_lock[symbol] = None

        _log_decision(
            symbol, price, momentum_raw, momentum, volatility,
            low_24h, high_24h,
            range_pos, 0.20, 0.30,
            prev_signal, last_sell,
            "BUY", "bear_market_mean_reversion_buy"
        )

        return _decision(symbol, "BUY", price, momentum, "bear_market_mean_reversion_buy")

    # --------------------------------------------------
    # SELL LOGIC — PROFIT LOCK LADDER
    # --------------------------------------------------
    if entry_price is not None:
        pnl_pct = (price - entry_price) / entry_price
        current_lock = _profit_lock.get(symbol)

        PROFIT_LOCKS = [
            (0.02, 0.00),
            (0.04, 0.02),
            (0.06, 0.04),
            (0.08, 0.06),
        ]

        for trigger, lock in PROFIT_LOCKS:
            if pnl_pct >= trigger:
                if current_lock is None or lock > current_lock:
                    _profit_lock[symbol] = lock
                    current_lock = lock

        # EXIT ON PROFIT LOCK BREACH
        if current_lock is not None and pnl_pct <= current_lock:
            _last_signal[symbol] = "SELL"
            _last_sell_price[symbol] = price
            _profit_lock.pop(symbol, None)

            _log_decision(
                symbol, price, momentum_raw, momentum, volatility,
                low_24h, high_24h,
                range_pos, 0.20, 0.30,
                prev_signal, last_sell,
                "SELL", f"profit_lock_exit_{int(current_lock*100)}pct"
            )

            return _decision(
                symbol,
                "SELL",
                price,
                momentum,
                f"profit_lock_exit_{int(current_lock*100)}pct"
            )

        # HARD STRUCTURAL FAILURE
        if z_score < -3.0:
            _last_signal[symbol] = "SELL"
            _last_sell_price[symbol] = price
            _profit_lock.pop(symbol, None)

            return _decision(symbol, "SELL", price, momentum, "structural_break_exit")

    # --------------------------------------------------
    # FALLBACK
    # --------------------------------------------------
    _last_signal[symbol] = "HOLD"
    return _decision(symbol, "HOLD", price, momentum, "neutral")


def _log_decision(
    symbol, price, mom_raw, mom_norm, vol,
    low_24h, high_24h,
    range_pos, lower_band, upper_band,
    prev_signal, last_sell,
    action, reason
):
    rp = f"{range_pos:.3f}" if range_pos is not None else "n/a"
    bands = f"{lower_band:.2f}-{upper_band:.2f}"

    logger.info(
        f"DECISION {symbol} | "
        f"price={price:.5f} | "
        f"mom_raw={mom_raw:.5f} | "
        f"mom_norm={mom_norm:.5f} | "
        f"vol={vol:.5f} | "
        f"24h_low={low_24h:.5f} | "
        f"24h_high={high_24h:.5f} | "
        f"range_pos={rp} | "
        f"bands={bands} | "
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

#     min_trades = cfg.get("min_trades", 1)
#     mom_threshold = cfg.get("momentum_threshold", 0.15)

#     prev_signal = _last_signal.get(symbol)
#     last_sell = _last_sell_price.get(symbol)

#     # ---------- EARLY EXIT: INSUFFICIENT TRADES ----------
#     if trades < min_trades:
#         _last_signal[symbol] = "HOLD"

#         _log_decision(
#             symbol, price, momentum_raw, momentum, volatility,
#             low_24h, high_24h,
#             None, None, None,
#             prev_signal, last_sell,
#             "HOLD", "insufficient_trades"
#         )
#         return _decision(symbol, "HOLD", price, momentum, "insufficient_trades")

#     # ---------- RANGE CALCULATION ----------
#     range_width = high_24h - low_24h
#     if range_width <= 0:
#         _last_signal[symbol] = "HOLD"

#         _log_decision(
#             symbol, price, momentum_raw, momentum, volatility,
#             low_24h, high_24h,
#             None, None, None,
#             prev_signal, last_sell,
#             "HOLD", "invalid_24h_range"
#         )
#         return _decision(symbol, "HOLD", price, momentum, "invalid_24h_range")

#     range_pos = (price - low_24h) / range_width

#     # ---------- SYMBOL-ADAPTIVE BANDS ----------
#     lower_band = 0.15
#     upper_band = 0.35

#     if range_width / max(low_24h, 1e-8) > 0.25:
#         lower_band = 0.15
#         upper_band = 0.35

#     # ---------- MOMENTUM SIGNAL ----------
#     if momentum > mom_threshold:
#         signal = "BUY"
#     elif momentum < -mom_threshold:
#         signal = "SELL"
#     else:
#         signal = "HOLD"

#     _last_signal[symbol] = signal

#     # ---------- CONFIRMATION RULE ----------
#     if prev_signal is None or signal != prev_signal:
#         _log_decision(
#             symbol, price, momentum_raw, momentum, volatility,
#             low_24h, high_24h,
#             range_pos, lower_band, upper_band,
#             prev_signal, last_sell,
#             "HOLD", "signal_not_confirmed"
#         )
#         return _decision(symbol, "HOLD", price, momentum, "signal_not_confirmed")

#     # ---------- BUY LOGIC ----------
#     # if signal == "BUY":
#     #     if range_pos > upper_band:
#     #         action, reason = "HOLD", "price_too_high_24h"
#     #     elif range_pos < lower_band:
#     #         action, reason = "HOLD", "falling_knife_guard"
#     #     elif last_sell is not None and price >= last_sell:
#     #         action, reason = "HOLD", "rebuy_blocked"
#     #     else:
#     #         action, reason = "BUY", "strategy_buy"
#     if signal == "BUY":
#     # --- Momentum breakout BUY ---
#       if range_pos > upper_band and momentum > mom_threshold * 1.5:
#         action, reason = "BUY", "momentum_breakout"

#     # --- Mean reversion BUY ---
#       elif range_pos < lower_band and momentum > mom_threshold:
#         action, reason = "BUY", "mean_reversion_buy"

#     # --- Rebuy protection (soft) ---
#       elif last_sell is not None and price >= last_sell * 1.002:
#         action, reason = "HOLD", "rebuy_cooldown"

#       else:
#         action, reason = "HOLD", "buy_conditions_not_met"

#         _log_decision(
#             symbol, price, momentum_raw, momentum, volatility,
#             low_24h, high_24h,
#             range_pos, lower_band, upper_band,
#             prev_signal, last_sell,
#             action, reason
#         )
#         return _decision(symbol, action, price, momentum, reason)

#     # ---------- SELL LOGIC ----------
#     if signal == "SELL":
#         _last_sell_price[symbol] = price

#         _log_decision(
#             symbol, price, momentum_raw, momentum, volatility,
#             low_24h, high_24h,
#             range_pos, lower_band, upper_band,
#             prev_signal, last_sell,
#             "SELL", "strategy_sell"
#         )
#         return _decision(symbol, "SELL", price, momentum, "strategy_sell")

#     # ---------- FALLBACK ----------
#     _log_decision(
#         symbol, price, momentum_raw, momentum, volatility,
#         low_24h, high_24h,
#         range_pos, lower_band, upper_band,
#         prev_signal, last_sell,
#         "HOLD", "neutral"
#     )
#     return _decision(symbol, "HOLD", price, momentum, "neutral")


# def _log_decision(
#     symbol, price, mom_raw, mom_norm, vol,
#     low_24h, high_24h,
#     range_pos, lower_band, upper_band,
#     prev_signal, last_sell,
#     action, reason
# ):
#     rp = f"{range_pos:.3f}" if range_pos is not None else "n/a"
#     bands = (
#         f"{lower_band:.2f}-{upper_band:.2f}"
#         if lower_band is not None else "n/a"
#     )

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




# from utils.logger import setup_logger

# logger = setup_logger("strategy")

# _last_signal = {}
# _last_sell_price = {}


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

#     min_trades = cfg.get("min_trades", 5)
#     mom_threshold = cfg.get("momentum_threshold", 0.15)

#     prev_signal = _last_signal.get(symbol)
#     last_sell = _last_sell_price.get(symbol)

#     # ---------- Guard: insufficient trades ----------
#     if trades < min_trades:
#         _log_decision(
#             symbol, price, momentum_raw, momentum, volatility,
#             low_24h, high_24h, None,
#             "HOLD", "insufficient_trades", prev_signal, last_sell
#         )
#         return _decision(symbol, "HOLD", price, momentum, "insufficient_trades")

#     # ---------- Range calculation ----------
#     range_width = high_24h - low_24h
#     if range_width <= 0:
#         _log_decision(
#             symbol, price, momentum_raw, momentum, volatility,
#             low_24h, high_24h, None,
#             "HOLD", "invalid_range", prev_signal, last_sell
#         )
#         return _decision(symbol, "HOLD", price, momentum, "invalid_range")

#     range_pos = (price - low_24h) / range_width

#     # ---------- Symbol-adaptive bands ----------
#     lower_band = 0.15
#     upper_band = 0.35

#     if range_width / low_24h > 0.25:
#         lower_band = 0.15
#         upper_band = 0.35

#     # ---------- Momentum signal ----------
#     if momentum > mom_threshold:
#         signal = "BUY"
#     elif momentum < -mom_threshold:
#         signal = "SELL"
#     else:
#         signal = "HOLD"

#     _last_signal[symbol] = signal

#     # ---------- Confirmation gate ----------
#     if signal != prev_signal:
#         _log_decision(
#             symbol, price, momentum_raw, momentum, volatility,
#             low_24h, high_24h, range_pos,
#             "HOLD", "signal_not_confirmed", prev_signal, last_sell,
#             lower_band, upper_band
#         )
#         return _decision(symbol, "HOLD", price, momentum, "signal_not_confirmed")

#     # ---------- BUY logic ----------
#     if signal == "BUY":
#         if range_pos > upper_band:
#             reason = "price_too_high_24h"
#             action = "HOLD"
#         elif range_pos < lower_band:
#             reason = "falling_knife_guard"
#             action = "HOLD"
#         elif last_sell and price >= last_sell:
#             reason = "rebuy_blocked"
#             action = "HOLD"
#         else:
#             reason = "strategy_buy"
#             action = "BUY"

#         _log_decision(
#             symbol, price, momentum_raw, momentum, volatility,
#             low_24h, high_24h, range_pos,
#             action, reason, prev_signal, last_sell,
#             lower_band, upper_band
#         )
#         return _decision(symbol, action, price, momentum, reason)

#     # ---------- SELL logic ----------
#     if signal == "SELL":
#         _last_sell_price[symbol] = price

#         _log_decision(
#             symbol, price, momentum_raw, momentum, volatility,
#             low_24h, high_24h, range_pos,
#             "SELL", "strategy_sell", prev_signal, last_sell,
#             lower_band, upper_band
#         )
#         return _decision(symbol, "SELL", price, momentum, "strategy_sell")

#     # ---------- Neutral ----------
#     _log_decision(
#         symbol, price, momentum_raw, momentum, volatility,
#         low_24h, high_24h, range_pos,
#         "HOLD", "neutral", prev_signal, last_sell,
#         lower_band, upper_band
#     )
#     return _decision(symbol, "HOLD", price, momentum, "neutral")


# def _log_decision(
#     symbol, price, mom_raw, mom_norm, vol,
#     low_24h, high_24h, range_pos,
#     action, reason, prev_signal, last_sell,
#     lower_band=None, upper_band=None
# ):
#     rp = f"{range_pos:.3f}" if range_pos is not None else "N/A"
#     bands = (
#         f"{lower_band:.2f}-{upper_band:.2f}"
#         if lower_band is not None and upper_band is not None
#         else "N/A"
#     )

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



# from utils.logger import setup_logger

# logger = setup_logger("strategy")

# # Persistent per-symbol memory
# _last_signal = {}
# _last_sell_price = {}


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

#     min_trades = cfg.get("min_trades", 5)
#     mom_threshold = cfg.get("momentum_threshold", 0.15)

#     # ------------------------
#     # Guardrails
#     # ------------------------

#     if trades < min_trades:
#         return _decision(symbol, "HOLD", price, momentum, "insufficient_trades")

#     range_width = high_24h - low_24h
#     if range_width <= 0:
#         return _decision(symbol, "HOLD", price, momentum, "invalid_24h_range")

#     range_pos = (price - low_24h) / range_width

#     # ------------------------
#     # Symbol-adaptive range bands
#     # ------------------------

#     # Default safe zone: 15%–35%
#     lower_band = 0.15
#     upper_band = 0.35

#     # Widen bands slightly for very volatile assets
#     if range_width / low_24h > 0.25:
#         lower_band = 0.10
#         upper_band = 0.40

#     # ------------------------
#     # Momentum → signal
#     # ------------------------

#     if momentum > mom_threshold:
#         signal = "BUY"
#     elif momentum < -mom_threshold:
#         signal = "SELL"
#     else:
#         signal = "HOLD"

#     prev_signal = _last_signal.get(symbol)
#     last_sell = _last_sell_price.get(symbol)

#     # Store current signal
#     _last_signal[symbol] = signal

#     # ------------------------
#     # Decision logging (FULL CONTEXT)
#     # ------------------------

#     logger.info(
#         f"DECISION {symbol} | "
#         f"price={price:.5f} | "
#         f"mom_raw={momentum_raw:.5f} | "
#         f"mom_norm={momentum:.5f} | "
#         f"vol={volatility:.5f} | "
#         f"24h_low={low_24h:.5f} | "
#         f"24h_high={high_24h:.5f} | "
#         f"range_pos={range_pos:.3f} | "
#         f"bands={lower_band:.2f}-{upper_band:.2f} | "
#         f"prev_signal={prev_signal} | "
#         f"last_sell={last_sell}"
#     )

#     # ------------------------
#     # Signal confirmation
#     # ------------------------

#     if signal != prev_signal:
#         return _decision(symbol, "HOLD", price, momentum, "signal_not_confirmed")

#     # ------------------------
#     # BUY logic
#     # ------------------------

#     if signal == "BUY":
#         if range_pos > upper_band:
#             return _decision(symbol, "HOLD", price, momentum, "price_too_high_24h")

#         if range_pos < lower_band:
#             return _decision(symbol, "HOLD", price, momentum, "falling_knife_guard")

#         if last_sell is not None and price >= last_sell:
#             return _decision(symbol, "HOLD", price, momentum, "rebuy_blocked")

#         return _decision(symbol, "BUY", price, momentum, "strategy_buy")

#     # ------------------------
#     # SELL logic
#     # ------------------------

#     if signal == "SELL":
#         _last_sell_price[symbol] = price
#         return _decision(symbol, "SELL", price, momentum, "strategy_sell")

#     # ------------------------
#     # Neutral
#     # ------------------------

#     return _decision(symbol, "HOLD", price, momentum, "neutral")


# def _decision(symbol: str, action: str, price: float, momentum: float, reason: str) -> dict:
#     logger.info(f"{symbol} → {action} | reason={reason}")
#     return {
#         "symbol": symbol,
#         "action": action,
#         "price": price,
#         "momentum": momentum,
#         "reason": reason,
#     }



# from utils.logger import setup_logger
# logger = setup_logger("strategy_ engine")

# def evaluate_symbol(symbol: str, market: dict, cfg: dict) -> dict | None:
#     """
#     Lightweight, Revolut-native strategy.
#     No candles. No indicators requiring OHLC.
#     """

#     price = market["price"]
#     mid = market["mid_price"]
#     spread = market["spread"]
#     momentum = market["momentum"]

#     max_spread_pct = cfg["strategy"].get("max_spread_pct", 0.002)
#     min_momentum = cfg["strategy"].get("min_momentum", 0.0005)

#     max_spread = price * max_spread_pct

#     if spread > max_spread:
#         logger.info(f"{symbol} skipped — spread too wide")
#         return None

#     score = 0

#     # Momentum
#     if momentum > min_momentum:
#         score += 1
#     elif momentum < -min_momentum:
#         score -= 1

#     # Mean reversion bias
#     if price < mid:
#         score += 1
#     else:
#         score -= 1

#     action = "HOLD"
#     if score >= 2:
#         action = "BUY"
#     elif score <= -2:
#         action = "SELL"

#     decision = {
#         "symbol": symbol,
#         "action": action,
#         "price": price,
#         "score": score,
#         "momentum": momentum,
#         "spread": spread,
#     }

#     logger.info(f"DECISION {symbol} → {action} (score={score})")
#     return decision



# from analysis.indicators import (
#     calculate_rsi,
#     moving_average,
#     calculate_volatility,
#     market_regime
# )
# from utils.logger import setup_logger

# logger = setup_logger()


# def evaluate_symbol(symbol, ohlcv, cfg):
#     """
#     Evaluates a symbol and returns a fully scored decision.
#     """

#     closes = ohlcv["close"]
#     price = closes[-1]

#     # =========================
#     # INDICATORS
#     # =========================
#     rsi = calculate_rsi(closes, period=14)
#     ma20 = moving_average(closes, 20)
#     ma50 = moving_average(closes, 50)
#     ma200 = moving_average(closes, 200)
#     vol = calculate_volatility(closes)

#     if rsi is None or ma20 is None or ma50 is None:
#         logger.info(f"⚠️ {symbol} insufficient data")
#         return _hold(symbol, price, rsi, vol, "INSUFFICIENT_DATA")

#     # =========================
#     # REGIME FILTER (NEW)
#     # =========================
#     regime = market_regime(closes)

#     if regime == "HIGH_VOL":
#         logger.info(f"🚫 {symbol} skipped — HIGH VOLATILITY")
#         return _hold(symbol, price, rsi, vol, regime)

#     # =========================
#     # TREND DETECTION
#     # =========================
#     trend = "NEUTRAL"
#     if ma20 > ma50 and (ma200 is None or ma50 > ma200):
#         trend = "BULL"
#     elif ma20 < ma50 and (ma200 is None or ma50 < ma200):
#         trend = "BEAR"

#     # =========================
#     # SCORING
#     # =========================
#     score = 0

#     # RSI mean reversion
#     if rsi < 30:
#         score += 40
#     elif rsi < 40:
#         score += 20
#     elif rsi > 70:
#         score -= 40
#     elif rsi > 60:
#         score -= 20

#     # Trend alignment
#     if trend == "BULL" and price > ma20:
#         score += 20
#     elif trend == "BEAR" and price < ma20:
#         score -= 20

#     # Regime constraint: no mean reversion in strong trend
#     if regime == "TREND" and rsi < 30:
#         logger.info(f"🚫 {symbol} blocked — TREND regime")
#         return _hold(symbol, price, rsi, vol, regime)

#     # =========================
#     # DECISION
#     # =========================
#     buy_threshold = cfg["strategy"]["buy_score"]
#     sell_threshold = cfg["strategy"]["sell_score"]

#     if score >= buy_threshold:
#         action = "BUY"
#     elif score <= -sell_threshold:
#         action = "SELL"
#     else:
#         action = "HOLD"

#     decision = {
#         "symbol": symbol,
#         "action": action,
#         "score": score,
#         "price": price,
#         "rsi": rsi,
#         "trend": trend,
#         "regime": regime,
#         "volatility": vol
#     }

#     logger.info(f"🧠 STRATEGY → {decision}")
#     return decision


# def _hold(symbol, price, rsi, vol, regime):
#     """
#     Standard HOLD decision
#     """
#     return {
#         "symbol": symbol,
#         "action": "HOLD",
#         "score": 0,
#         "price": price,
#         "rsi": rsi,
#         "trend": "UNKNOWN",
#         "regime": regime,
#         "volatility": vol
#     }
