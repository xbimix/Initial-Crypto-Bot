from api.revolut_trades import get_last_trades
from utils.logger import setup_logger
import statistics

logger = setup_logger("market_data")


def fetch_market_snapshot(symbol: str, cfg: dict) -> dict | None:
    """
    Revolut-first market snapshot.
    Trade-based only. No candles. No OHLC assumptions.
    Produces normalized momentum + volatility + 24h range.
    """

    try:
        asset = symbol.split("-")[0]
        lookback = cfg.get("lookback", 200)  # slightly larger for stability

        logger.info(f"📘 Fetching last trades for {asset}")

        trades = get_last_trades(limit=lookback)
        trades = [t for t in trades if t.get("aid") == asset]

        if len(trades) < 2:
            logger.warning(f"Not enough trades for {symbol}")
            return None

        prices = [float(t["p"]) for t in trades]

        # Trades are newest-first from Revolut
        last_price = prices[0]
        first_price = prices[-1]

        # --- Volatility proxy (trade-based, candle-free) ---
        price_changes = [
            abs(prices[i] - prices[i + 1])
            for i in range(len(prices) - 1)
        ]

        volatility = statistics.mean(price_changes) if price_changes else 0.0

        # --- Normalized momentum ---
        raw_momentum = (
            (last_price - first_price) / first_price
            if first_price > 0
            else 0.0
        )

        norm_momentum = (
            raw_momentum / volatility
            if volatility > 0
            else 0.0
        )

        # --- 24h range approximation (trade-derived, safe) ---
        high_24h = max(prices)
        low_24h = min(prices)

        snapshot = {
            "symbol": symbol,
            "price": last_price,
            "momentum_raw": raw_momentum,
            "momentum_norm": norm_momentum,
            "volatility": volatility,
            "trade_count": len(prices),

            # NEW (required by strategy)
            "high_24h": high_24h,
            "low_24h": low_24h,
        }

        logger.info(
            f"SNAPSHOT {symbol} | "
            f"price={last_price:.4f} "
            f"raw_mom={raw_momentum:.5f} "
            f"norm_mom={norm_momentum:.3f} "
            f"vol={volatility:.6f} "
            f"trades={len(prices)} "
            f"24h_low={low_24h:.4f} "
            f"24h_high={high_24h:.4f}"
        )

        return snapshot

    except Exception as e:
        logger.exception(f"Market snapshot error for {symbol}: {e}")
        return None


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
