import time
import statistics
from collections import defaultdict, deque
from datetime import datetime

from api.revolut_order_book import get_order_book
from api.revolut_trades import get_last_trades
from utils.logger import setup_logger

logger = setup_logger("market_data")

EPSILON = 1e-8
SECONDS_24H = 86400
DEFAULT_ATR_FLOOR = 0.0
DEFAULT_MAX_TRADE_JUMP_PCT = 0.12
FUTURE_TRADE_TOLERANCE = 5
DEFAULT_HISTORY_SECONDS = SECONDS_24H
DEFAULT_MIN_HISTORY_POINTS = 8
DEFAULT_MAX_SPREAD_BPS = 150.0
DEFAULT_MAX_BOOK_TRADE_GAP_PCT = 0.02
DEFAULT_TRADE_CONFIRMATION_LIMIT = 100

_PRICE_HISTORY = defaultdict(deque)


def _parse_ts(payload) -> float | None:
    if isinstance(payload, dict):
        iso = payload.get("tdt") or payload.get("pdt") or payload.get("timestamp")
    else:
        iso = payload

    if not iso:
        return None

    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _split_symbol(symbol: str) -> tuple[str, str]:
    base, quote = symbol.split("-", 1)
    return base.upper(), quote.upper()


def _ema(values, period):
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    ema_val = values[0]

    for price in values[1:]:
        ema_val = price * k + ema_val * (1 - k)

    return ema_val


def _parse_size(trade: dict) -> float:
    for key in ("q", "s", "sz", "size", "amount", "v"):
        raw = trade.get(key)
        if raw is None:
            continue
        try:
            size = float(raw)
            if size > 0:
                return size
        except (TypeError, ValueError):
            continue
    return 1.0


def _matches_symbol_row(row: dict, base: str, quote: str) -> bool:
    aid = str(row.get("aid", "")).upper()
    price_ccy = str(row.get("pc", "")).upper()
    qty_ccy = str(row.get("qc", "")).upper()

    return aid == base and price_ccy == quote and qty_ccy == base


def _weighted_average(prices, sizes):
    total_size = sum(sizes)
    if total_size <= 0:
        return statistics.mean(prices)
    return sum(p * s for p, s in zip(prices, sizes)) / total_size


def _filter_price_jumps(trades: list[dict], max_jump_pct: float) -> tuple[list[dict], int]:
    if len(trades) < 2 or max_jump_pct <= 0:
        return trades, 0

    filtered = [trades[0]]
    skipped = 0

    for trade in trades[1:]:
        prev_price = filtered[-1]["price"]
        jump_pct = abs(trade["price"] - prev_price) / (prev_price + EPSILON)
        if jump_pct > max_jump_pct:
            skipped += 1
            continue
        filtered.append(trade)

    return filtered, skipped


def _parse_book_levels(
    levels: list[dict] | None,
    base: str,
    quote: str,
    expected_side: str,
) -> list[dict]:
    parsed = []

    if not isinstance(levels, list):
        return parsed

    for level in levels:
        if not _matches_symbol_row(level, base, quote):
            continue

        side = str(level.get("s", "")).upper()
        if side:
            if expected_side == "BUYI" and not side.startswith("BUY"):
                continue
            if expected_side == "SELL" and side != "SELL":
                continue

        try:
            price = float(level["p"])
            size = float(level["q"])
        except (KeyError, TypeError, ValueError):
            continue

        if price <= 0 or size <= 0:
            continue

        parsed.append(
            {
                "price": price,
                "size": size,
                "ts": _parse_ts(level),
            }
        )

    return parsed


def _extract_order_book_snapshot(payload: dict, symbol: str) -> dict | None:
    base, quote = _split_symbol(symbol)
    data = payload.get("data", {}) if isinstance(payload, dict) else {}

    asks = _parse_book_levels(data.get("asks"), base, quote, "SELL")
    bids = _parse_book_levels(data.get("bids"), base, quote, "BUYI")

    if not asks or not bids:
        logger.warning(f"No valid order book levels for {symbol}")
        return None

    best_ask = min(asks, key=lambda level: level["price"])
    best_bid = max(bids, key=lambda level: level["price"])

    if best_ask["price"] <= best_bid["price"]:
        logger.warning(
            f"Crossed order book for {symbol}: "
            f"bid={best_bid['price']:.5f} ask={best_ask['price']:.5f}"
        )
        return None

    mid_price = (best_bid["price"] + best_ask["price"]) / 2
    spread = best_ask["price"] - best_bid["price"]
    spread_bps = (spread / (mid_price + EPSILON)) * 10000

    top_bid_size = best_bid["size"]
    top_ask_size = best_ask["size"]
    microprice = (
        ((best_ask["price"] * top_bid_size) + (best_bid["price"] * top_ask_size))
        / (top_bid_size + top_ask_size + EPSILON)
    )

    total_bid_depth = sum(level["size"] for level in bids)
    total_ask_depth = sum(level["size"] for level in asks)
    depth_weight = total_bid_depth + total_ask_depth

    snapshot_ts = _parse_ts(payload.get("metadata", {})) if isinstance(payload, dict) else None
    snapshot_ts = snapshot_ts or best_ask["ts"] or best_bid["ts"] or time.time()

    return {
        "best_bid": best_bid["price"],
        "best_ask": best_ask["price"],
        "mid_price": mid_price,
        "microprice": microprice,
        "spread": spread,
        "spread_bps": spread_bps,
        "timestamp": snapshot_ts,
        "top_bid_size": top_bid_size,
        "top_ask_size": top_ask_size,
        "bid_depth": total_bid_depth,
        "ask_depth": total_ask_depth,
        "depth_weight": depth_weight,
        "book_imbalance": total_bid_depth / (depth_weight + EPSILON),
    }


def _parse_symbol_trades(
    symbol: str,
    base: str,
    quote: str,
    limit: int,
    max_trade_jump_pct: float,
) -> tuple[list[dict], int]:
    trades = get_last_trades(symbol=symbol, limit=limit)
    if not isinstance(trades, list):
        return [], 0

    parsed = []
    for trade in trades:
        if not _matches_symbol_row(trade, base, quote):
            continue

        ts = _parse_ts(trade)
        if ts is None or ts > time.time() + FUTURE_TRADE_TOLERANCE:
            continue

        try:
            price = float(trade["p"])
            if price <= 0:
                continue
        except (KeyError, TypeError, ValueError):
            continue

        parsed.append(
            {
                "price": price,
                "ts": ts,
                "size": _parse_size(trade),
            }
        )

    parsed.sort(key=lambda item: item["ts"])
    return _filter_price_jumps(parsed, max_trade_jump_pct)


def _record_mark_price(
    symbol: str,
    snapshot_ts: float,
    mark_price: float,
    weight: float,
    history_seconds: int,
) -> list[dict]:
    history = _PRICE_HISTORY[symbol]
    sample = {
        "ts": snapshot_ts,
        "price": mark_price,
        "weight": max(weight, 1.0),
    }

    if history and abs(history[-1]["ts"] - snapshot_ts) < 1e-6:
        history[-1] = sample
    else:
        history.append(sample)

    cutoff = snapshot_ts - history_seconds
    while history and history[0]["ts"] < cutoff:
        history.popleft()

    return list(history)


def fetch_market_snapshot(symbol: str, cfg: dict) -> dict | None:
    try:
        lookback = cfg.get("lookback", 200)
        base, quote = _split_symbol(symbol)
        volatility_cfg = cfg.get("volatility_filters", {})
        market_data_cfg = cfg.get("market_data", {})
        atr_floor = volatility_cfg.get("atr_floor", cfg.get("atr_floor", DEFAULT_ATR_FLOOR))
        max_trade_jump_pct = volatility_cfg.get(
            "max_trade_jump_pct",
            cfg.get("max_trade_jump_pct", DEFAULT_MAX_TRADE_JUMP_PCT),
        )
        history_seconds = int(market_data_cfg.get("history_seconds", DEFAULT_HISTORY_SECONDS))
        min_history_points = int(
            market_data_cfg.get("min_history_points", DEFAULT_MIN_HISTORY_POINTS)
        )
        max_spread_bps = float(market_data_cfg.get("max_spread_bps", DEFAULT_MAX_SPREAD_BPS))
        max_book_trade_gap_pct = float(
            market_data_cfg.get(
                "max_book_trade_gap_pct",
                DEFAULT_MAX_BOOK_TRADE_GAP_PCT,
            )
        )
        trade_confirmation_limit = int(
            market_data_cfg.get(
                "trade_confirmation_limit",
                DEFAULT_TRADE_CONFIRMATION_LIMIT,
            )
        )
        trade_confirmation_limit = max(0, min(trade_confirmation_limit, max(1, min(lookback, 100))))

        logger.info(f"Fetching market snapshot for {symbol}")
        order_book = get_order_book(symbol)
        book = _extract_order_book_snapshot(order_book, symbol)
        if book is None:
            return None

        history = _record_mark_price(
            symbol,
            book["timestamp"],
            book["mid_price"],
            book["depth_weight"],
            history_seconds,
        )

        prices = [sample["price"] for sample in history]
        weights = [sample["weight"] for sample in history]
        first_price = prices[0]
        last_price = book["mid_price"]

        quality_reasons = []
        if book["spread_bps"] > max_spread_bps:
            quality_reasons.append("spread_too_wide")

        if len(history) < min_history_points:
            quality_reasons.append("warming_up_history")

        filtered_trades = []
        latest_trade_price = None
        if trade_confirmation_limit > 0:
            filtered_trades, skipped_outliers = _parse_symbol_trades(
                symbol=symbol,
                base=base,
                quote=quote,
                limit=trade_confirmation_limit,
                max_trade_jump_pct=max_trade_jump_pct,
            )
            if skipped_outliers:
                logger.info(
                    f"Filtered {skipped_outliers} outlier tape prints for {symbol} "
                    f"(max_jump_pct={max_trade_jump_pct:.3f})"
                )

            if filtered_trades:
                latest_trade_price = filtered_trades[-1]["price"]
                trade_gap_pct = abs(latest_trade_price - last_price) / (last_price + EPSILON)
                if trade_gap_pct > max_book_trade_gap_pct:
                    quality_reasons.append("order_book_tape_mismatch")

        deltas = [
            abs(prices[i] - prices[i - 1]) / prices[i - 1]
            for i in range(1, len(prices))
            if prices[i - 1] > 0
        ]

        atr_raw = statistics.median(deltas) if deltas else 0.0
        atr = max(atr_raw, atr_floor)

        vwap = _weighted_average(prices, weights)
        median_price = statistics.median(prices)

        raw_momentum = (last_price - first_price) / (first_price + EPSILON)
        norm_momentum = raw_momentum / (atr + EPSILON)

        ema_50 = _ema(prices[-100:], 50)
        ema_200 = _ema(prices[-250:], 200)

        ema_50_prev = (
            _ema(prices[-101:-1], 50)
            if len(prices) > 101
            else None
        )

        ema_50_slope = None
        if ema_50 is not None and ema_50_prev is not None:
            ema_50_slope = ema_50 - ema_50_prev

        high_24h = max(prices)
        low_24h = min(prices)
        data_quality_ok = not quality_reasons
        data_quality_reason = ",".join(quality_reasons) if quality_reasons else "ok"

        snapshot = {
            "symbol": symbol,
            "price": last_price,
            "best_bid": book["best_bid"],
            "best_ask": book["best_ask"],
            "mid_price": book["mid_price"],
            "microprice": book["microprice"],
            "spread": book["spread"],
            "spread_bps": book["spread_bps"],
            "book_imbalance": book["book_imbalance"],
            "latest_trade_price": latest_trade_price,
            "price_source": "order_book_mid",
            "momentum_raw": raw_momentum,
            "momentum_norm": norm_momentum,

            "atr": atr,
            "atr_raw": atr_raw,
            "volatility": atr,

            "vwap": vwap,
            "median_price": median_price,
            "high_24h": high_24h,
            "low_24h": low_24h,
            "trade_count": len(prices) if data_quality_ok else 0,
            "history_points": len(prices),
            "data_quality_ok": data_quality_ok,
            "data_quality_reason": data_quality_reason,

            "ema_50": ema_50,
            "ema_200": ema_200,
            "ema_50_slope": ema_50_slope,
        }

        logger.info(
            f"SNAPSHOT {symbol} | "
            f"price={last_price:.5f} "
            f"bid={book['best_bid']:.5f} "
            f"ask={book['best_ask']:.5f} "
            f"spread_bps={book['spread_bps']:.2f} "
            f"mom_norm={norm_momentum:.3f} "
            f"atr_raw={atr_raw:.5f} "
            f"vwap={vwap:.5f} "
            f"points={len(prices)} "
            f"quality={data_quality_reason} "
            f"24h_low={low_24h:.5f} "
            f"24h_high={high_24h:.5f}"
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

