# strategy/strategy_engine.py

from utils.logger import setup_logger
logger = setup_logger("strategy_ engine")



def evaluate_symbol(symbol: str, market: dict, cfg: dict) -> dict:
    """
    Strategy decision engine.
    Works with Revolut public-data snapshots (spread may be None).
    """

    price = market["price"]
    momentum = market.get("momentum", 0.0)
    spread = market.get("spread")  # May be None

    # --- Config thresholds ---
    buy_momentum = cfg.get("buy_momentum", 0.002)
    sell_momentum = cfg.get("sell_momentum", -0.002)
    max_spread = cfg.get("max_spread")  # Optional

    action = "HOLD"
    reason = "no_signal"

    # --- Spread filter (ONLY if spread exists) ---
    if spread is not None and max_spread is not None:
        if spread > max_spread:
            logger.info(
                f"{symbol} skipped | spread {spread:.4f} > max {max_spread:.4f}"
            )
            return {
                "symbol": symbol,
                "action": "HOLD",
                "price": price,
                "reason": "spread_filter",
            }

    # --- Momentum-based logic ---
    if momentum >= buy_momentum:
        action = "BUY"
        reason = "positive_momentum"

    elif momentum <= sell_momentum:
        action = "SELL"
        reason = "negative_momentum"

    logger.info(
        f"DECISION {symbol} | action={action} "
        f"momentum={momentum:.5f} reason={reason}"
    )

    return {
        "symbol": symbol,
        "action": action,
        "price": price,
        "momentum": momentum,
        "spread": spread,
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
