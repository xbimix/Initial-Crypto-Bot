from utils.logger import setup_logger

logger = setup_logger("strategy_engine")

# --- Stateful memory (minimal & intentional) ---
_last_signal = {}        # symbol -> "BUY" | "SELL" | None
_last_sell_price = {}   # symbol -> float


def evaluate_symbol(symbol: str, market: dict, cfg: dict) -> dict:
    """
    Regime-aware, trade-first strategy.
    - Momentum persistence
    - 24h range price gating
    - No rebuy above last sell
    - Revolut-native (no candles)
    """

    price = market["price"]
    trade_count = market.get("trade_count", 0)
    volatility = market.get("volatility", 0.0)
    momentum = market.get("momentum_norm", 0.0)

    # Optional but REQUIRED for the new rule
    high_24h = market.get("high_24h")
    low_24h = market.get("low_24h")

    # --- Config ---
    min_trades = cfg.get("min_trades", 15)
    min_volatility = cfg.get("min_volatility", 0.0001)
    momentum_threshold = cfg.get("momentum_threshold", 0.7)

    action = "HOLD"
    reason = "no_signal"

    # --- Trade quality gate ---
    if trade_count < min_trades:
        reason = "low_trade_count"
        logger.info(f"{symbol} HOLD | trades={trade_count} < {min_trades}")
        return _decision(symbol, action, price, momentum, reason)

    # --- Volatility gate ---
    if volatility < min_volatility:
        reason = "low_volatility"
        logger.info(f"{symbol} HOLD | volatility={volatility:.6f} < {min_volatility}")
        return _decision(symbol, action, price, momentum, reason)

    # --- Raw momentum signal ---
    signal = None
    if momentum >= momentum_threshold:
        signal = "BUY"
    elif momentum <= -momentum_threshold:
        signal = "SELL"

    # --- Momentum persistence (2-tick confirmation) ---
    prev_signal = _last_signal.get(symbol)

    if signal is None:
        _last_signal[symbol] = None
        return _decision(symbol, "HOLD", price, momentum, "no_momentum")

    if signal != prev_signal:
        _last_signal[symbol] = signal
        logger.info(f"{symbol} signal armed: {signal}")
        return _decision(symbol, "HOLD", price, momentum, "signal_not_confirmed")

    # Signal confirmed
    _last_signal[symbol] = None

    # --- 24h range gate (BUY only near lows) ---
    if signal == "BUY" and high_24h and low_24h and high_24h > low_24h:
        range_pos = (price - low_24h) / (high_24h - low_24h)

        if range_pos > 0.30:
            reason = "price_too_high_in_24h_range"
            logger.info(f"{symbol} BUY blocked | range_pos={range_pos:.2f}")
            return _decision(symbol, "HOLD", price, momentum, reason)

        if range_pos < 0.10:
            reason = "falling_knife_risk"
            logger.info(f"{symbol} BUY blocked | range_pos={range_pos:.2f}")
            return _decision(symbol, "HOLD", price, momentum, reason)

    # --- No rebuy above last sell ---
    if signal == "BUY":
        last_sell = _last_sell_price.get(symbol)
        if last_sell and price >= last_sell:
            reason = "rebuy_above_last_sell"
            logger.info(f"{symbol} BUY blocked | price={price} >= last_sell={last_sell}")
            return _decision(symbol, "HOLD", price, momentum, reason)

    # --- Final action ---
    action = signal
    reason = "strategy_buy" if signal == "BUY" else "strategy_sell"

    if action == "SELL":
        _last_sell_price[symbol] = price

    logger.info(
        f"DECISION {symbol} | "
        f"action={action} "
        f"price={price} "
        f"momentum={momentum:.3f} "
        f"vol={volatility:.6f} "
        f"trades={trade_count} "
        f"reason={reason}"
    )

    return _decision(symbol, action, price, momentum, reason)


def _decision(symbol, action, price, momentum, reason):
    return {
        "symbol": symbol,
        "action": action,
        "price": price,
        "momentum": momentum,
        "reason": reason,
    }




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
