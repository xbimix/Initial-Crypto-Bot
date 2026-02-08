import time
import statistics
from datetime import datetime
from api.revolut_trades import get_last_trades
from utils.logger import setup_logger

logger = setup_logger("market_data")

EPSILON = 1e-8
SECONDS_24H = 86400


def _parse_ts(trade: dict) -> float | None:
    iso = trade.get("tdt") or trade.get("pdt")
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def fetch_market_snapshot(symbol: str, cfg: dict) -> dict | None:
    try:
        asset = symbol.split("-")[0]
        lookback = cfg.get("lookback", 200)
        min_trades = cfg.get("min_trades", 3)

        logger.info(f"📘 Fetching last trades for {symbol}")
        trades = get_last_trades(symbol=symbol, limit=lookback)

        parsed = []
        for t in trades:
            if t.get("aid") != asset or "p" not in t:
                continue

            ts = _parse_ts(t)
            if ts is None:
                continue

            try:
                price = float(t["p"])
                if price <= 0:
                    continue
            except Exception:
                continue

            parsed.append({"price": price, "ts": ts})

        if len(parsed) < min_trades:
            logger.warning(f"Not enough valid trades for {symbol}")
            return None

        # --- SORT OLDEST → NEWEST ---
        parsed.sort(key=lambda x: x["ts"])

        now = time.time()
        last_24h = [t for t in parsed if now - t["ts"] <= SECONDS_24H]

        if len(last_24h) < min_trades:
            logger.warning(f"Not enough 24h trades for {symbol}")
            return None

        prices = [t["price"] for t in last_24h]

        first_price = prices[0]
        last_price = prices[-1]

        # --- ATR-LIKE VOLATILITY (ROBUST TO SPIKES) ---
        deltas = [
            abs(prices[i] - prices[i - 1]) / prices[i - 1]
            for i in range(1, len(prices))
            if prices[i - 1] > 0
        ]

        atr_proxy = statistics.median(deltas) if deltas else 0.0

        # --- VWAP PROXY ---
        vwap = statistics.mean(prices)
        median_price = statistics.median(prices)

        raw_momentum = (last_price - first_price) / first_price

        # clamp normalization to avoid explosion
        norm_momentum = raw_momentum / max(atr_proxy, 0.002)

        high_24h = max(prices)
        low_24h = min(prices)

        snapshot = {
            "symbol": symbol,
            "price": last_price,
            "momentum_raw": raw_momentum,
            "momentum_norm": norm_momentum,
            "volatility": atr_proxy,
            "vwap": vwap,
            "median_price": median_price,
            "trade_count": len(prices),
            "high_24h": high_24h,
            "low_24h": low_24h,
        }

        logger.info(
            f"SNAPSHOT {symbol} | price={last_price:.5f} "
            f"mom_raw={raw_momentum:.4f} mom_norm={norm_momentum:.3f} "
            f"atr={atr_proxy:.5f} vwap={vwap:.5f} "
            f"24h_low={low_24h:.5f} 24h_high={high_24h:.5f}"
        )

        return snapshot

    except Exception as e:
        logger.exception(f"Market snapshot error for {symbol}: {e}")
        return None




# import time
# import statistics
# from datetime import datetime
# from api.revolut_trades import get_last_trades
# from utils.logger import setup_logger

# logger = setup_logger("market_data")

# EPSILON = 1e-8
# SECONDS_24H = 86400


# def _parse_ts(trade: dict) -> float | None:
#     """
#     Convert Revolut ISO timestamp (tdt / pdt) to epoch seconds.
#     """
#     iso = trade.get("tdt") or trade.get("pdt")
#     if not iso:
#         return None
#     try:
#         return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
#     except Exception:
#         return None


# def fetch_market_snapshot(symbol: str, cfg: dict) -> dict | None:
#     try:
#         asset = symbol.split("-")[0]
#         lookback = cfg.get("lookback", 200)
#         min_trades = cfg.get("min_trades", 3)

#         logger.info(f"📘 Fetching last trades for {symbol}")
#         trades = get_last_trades(symbol=symbol, limit=lookback)

#         parsed = []
#         for t in trades:
#             if t.get("aid") != asset or "p" not in t:
#                 continue

#             ts = _parse_ts(t)
#             if ts is None:
#                 continue

#             try:
#                 price = float(t["p"])
#                 if price <= 0:
#                     continue
#             except Exception:
#                 continue

#             parsed.append(
#                 {
#                     "price": price,
#                     "ts": ts,
#                 }
#             )

#         logger.info(f"{symbol} RAW TRADE SAMPLE: {parsed[:3]}")

#         if len(parsed) < min_trades:
#             logger.warning(
#                 f"Not enough valid trades for {symbol} ({len(parsed)} < {min_trades})"
#             )
#             return None

#         parsed.sort(key=lambda x: x["ts"], reverse=True)

#         now = time.time()
#         last_24h = [t for t in parsed if now - t["ts"] <= SECONDS_24H]

#         if len(last_24h) < min_trades:
#             logger.warning(f"Not enough 24h trades for {symbol}")
#             return None

#         prices = [t["price"] for t in last_24h]

#         last_price = prices[0]
#         first_price = prices[-1]

#         pct_changes = [
#             abs((prices[i] - prices[i + 1]) / prices[i + 1])
#             for i in range(len(prices) - 1)
#             if prices[i + 1] > 0
#         ]

#         volatility = statistics.mean(pct_changes) if pct_changes else 0.0
#         raw_momentum = (last_price - first_price) / first_price
#         norm_momentum = raw_momentum / (volatility + EPSILON)

#         high_24h = max(prices)
#         low_24h = min(prices)

#         snapshot = {
#             "symbol": symbol,
#             "price": last_price,
#             "momentum_raw": raw_momentum,
#             "momentum_norm": norm_momentum,
#             "volatility": volatility,
#             "trade_count": len(prices),
#             "high_24h": high_24h,
#             "low_24h": low_24h,
#         }

#         logger.info(
#             f"SNAPSHOT {symbol} | price={last_price:.4f} "
#             f"raw_mom={raw_momentum:.5f} norm_mom={norm_momentum:.3f} "
#             f"vol={volatility:.6f} trades={len(prices)} "
#             f"24h_low={low_24h:.4f} 24h_high={high_24h:.4f}"
#         )

#         return snapshot

#     except Exception as e:
#         logger.exception(f"Market snapshot error for {symbol}: {e}")
#         return None


# import statistics
# import time
# from api.revolut_trades import get_last_trades
# from utils.logger import setup_logger

# logger = setup_logger("market")

# EPSILON = 1e-8


# def fetch_market_snapshot(symbol: str, cfg: dict) -> dict | None:
#     try:
#         lookback = cfg.get("lookback", 200)
#         min_trades = cfg.get("min_trades", 3)
#         EPSILON = 1e-8

#         logger.info(f"📘 Fetching last trades for {symbol}")

#         # 🔑 CRITICAL FIX: symbol-scoped request
#         trades = get_last_trades(symbol=symbol, limit=lookback)

#         if not trades:
#             logger.warning(f"No trades returned from API for {symbol}")
#             return None

#         # Log raw diagnostics once
#         logger.info(f"{symbol} RAW TRADE SAMPLE: {trades[:3]}")

#         # Validate trade structure
#         valid_trades = [
#             t for t in trades
#             if "p" in t and "ts" in t
#         ]

#         if len(valid_trades) < min_trades:
#             logger.warning(
#                 f"Not enough valid trades for {symbol} "
#                 f"({len(valid_trades)} < {min_trades})"
#             )
#             return None

#         # Sort newest → oldest
#         valid_trades.sort(key=lambda x: x["ts"], reverse=True)

#         # ⏱️ 24h window
#         now = time.time()
#         trades_24h = [
#             t for t in valid_trades
#             if now - t["ts"] <= 86400
#         ]

#         if len(trades_24h) < min_trades:
#             logger.warning(
#                 f"Not enough 24h trades for {symbol} "
#                 f"({len(trades_24h)} < {min_trades})"
#             )
#             return None

#         # Prices
#         prices = []
#         for t in trades_24h:
#             try:
#                 p = float(t["p"])
#                 if p > 0:
#                     prices.append(p)
#             except Exception:
#                 continue

#         if len(prices) < min_trades:
#             logger.warning(f"Invalid price data for {symbol}")
#             return None

#         last_price = prices[0]
#         first_price = prices[-1]

#         # 📊 Volatility (percentage change based)
#         pct_changes = [
#             abs((prices[i] - prices[i + 1]) / prices[i + 1])
#             for i in range(len(prices) - 1)
#             if prices[i + 1] > 0
#         ]

#         volatility = (
#             statistics.mean(pct_changes)
#             if pct_changes else 0.0
#         )

#         raw_momentum = (last_price - first_price) / first_price
#         norm_momentum = raw_momentum / (volatility + EPSILON)

#         high_24h = max(prices)
#         low_24h = min(prices)

#         snapshot = {
#             "symbol": symbol,
#             "price": last_price,
#             "momentum_raw": raw_momentum,
#             "momentum_norm": norm_momentum,
#             "volatility": volatility,
#             "trade_count": len(prices),
#             "high_24h": high_24h,
#             "low_24h": low_24h,
#         }

#         logger.info(
#             f"SNAPSHOT {symbol} | "
#             f"price={last_price:.4f} "
#             f"raw_mom={raw_momentum:.5f} "
#             f"norm_mom={norm_momentum:.3f} "
#             f"vol={volatility:.6f} "
#             f"trades={len(prices)} "
#             f"24h_low={low_24h:.4f} "
#             f"24h_high={high_24h:.4f}"
#         )

#         return snapshot

#     except Exception as e:
#         logger.exception(f"Market snapshot error for {symbol}: {e}")
#         return None



# from api.revolut_trades import get_last_trades
# from api.revolut_order_book import get_order_book
# from utils.logger import setup_logger
# logger = setup_logger("market_data")
# def fetch_market_snapshot(symbol: str, cfg: dict) -> dict | None:
#     """
#     Revolut-first market snapshot.
#     Uses:
#     - public last trades (filtered client-side)
#     - public order book
#     No candles. No OHLC assumptions.
#     """

#     try:
#         base_asset = symbol.split("-")[0]  # BTC-USDT -> BTC
#         lookback = cfg.get("lookback", 100)

#         # --- Trades (Revolut has NO symbol filter at API level)
#         all_trades = get_last_trades(limit=lookback)
#         trades = [t for t in all_trades if t.get("aid") == base_asset]

#         if not trades:
#             logger.warning(f"No trades for {symbol}")
#             return None

#         prices = [float(t["p"]) for t in trades]
#         last_price = prices[0]

#         # Simple momentum (recent vs oldest)
#         momentum = (prices[0] - prices[-1]) / prices[-1]

#         # --- Order book (symbol IS required here)
#         rev_symbol = symbol.replace("USDT", "USD")
#         book = get_order_book(rev_symbol)
        
#         if not book or not book.get("bids") or not book.get("asks"):
#             logger.warning(f"No order book for {symbol}")
#             return None

#         best_bid = float(book["bids"][0]["p"])
#         best_ask = float(book["asks"][0]["p"])
#         spread = best_ask - best_bid
#         mid_price = (best_bid + best_ask) / 2

#         snapshot = {
#             "symbol": symbol,
#             "price": last_price,
#             "mid_price": mid_price,
#             "spread": spread,
#             "momentum": momentum,
#             "prices": prices,
#             "trade_count": len(trades),
#         }

#         logger.info(
#             f"SNAPSHOT {symbol} | "
#             f"price={last_price:.2f} "
#             f"spread={spread:.4f} "
#             f"momentum={momentum:.5f} "
#             f"trades={len(trades)}"
#         )

#         return snapshot

#     except Exception as e:
#         logger.exception(f"Market snapshot error for {symbol}: {e}")
#         return None


# from collections import defaultdict
# from datetime import datetime, timedelta
# from api.revolut_trades import get_last_trades
# from utils.logger import logger

# def _bucket_time(ts: datetime, minutes: int) -> datetime:
#     discard = timedelta(
#         minutes=ts.minute % minutes,
#         seconds=ts.second,
#         microseconds=ts.microsecond,
#     )
#     return ts - discard

# def fetch_ohlcv(symbol: str, timeframe_minutes: int = 15, limit: int = 100):
#     """
#     Build OHLCV candles from Revolut last trades.
#     """
#     trades = get_last_trades(limit=limit)
#     if not trades:
#         logger.warning("⚠️ No trades received")
#         return []

#     buckets = defaultdict(list)

#     for t in trades:
#         if t["aid"] != symbol.split("-")[0]:
#             continue

#         price = float(t["p"])
#         qty = float(t["q"])
#         ts = datetime.fromisoformat(t["tdt"].replace("Z", "+00:00"))

#         bucket = _bucket_time(ts, timeframe_minutes)
#         buckets[bucket].append((price, qty))

#     candles = []

#     for ts in sorted(buckets.keys()):
#         prices = [p for p, _ in buckets[ts]]
#         volume = sum(q for _, q in buckets[ts])

#         candles.append({
#             "timestamp": ts,
#             "open": prices[0],
#             "high": max(prices),
#             "low": min(prices),
#             "close": prices[-1],
#             "volume": volume,
#         })

#     logger.info(f"📊 Built {len(candles)} candles for {symbol}")
#     return candles
