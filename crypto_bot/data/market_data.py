import time
import statistics
from collections import defaultdict, deque
from datetime import datetime

from api.revolut_order_book import get_order_book
from api.revolut_trades import get_last_trades
from data.market_data_service import get_candle_meta, get_candles
from data.revolut_incremental_sync import sync_new_candles
from utils.logger import setup_logger

try:
    from analysis.indicators import calculate_rsi
except ModuleNotFoundError:
    from crypto_bot.analysis.indicators import calculate_rsi

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
DEFAULT_CANDLE_TIMEFRAME = "1m"
DEFAULT_CANDLE_HISTORY_LIMIT = 6_000
DEFAULT_CANDLE_SYNC_ENABLED = False
DEFAULT_CANDLE_SYNC_INTERVAL_SECONDS = 20
DEFAULT_REGIME_CORE_TIMEFRAMES = ("1h", "4h", "1d")
DEFAULT_REGIME_MIN_CANDLES = {"1h": 300, "4h": 180, "1d": 120}
DEFAULT_REGIME_STALE_AFTER_SECONDS = {"1h": 7200, "4h": 28800, "1d": 172800}

_PRICE_HISTORY = defaultdict(deque)
_LAST_CANDLE_SYNC_AT: dict[str, float] = {}
_INDICATOR_CACHE: dict[str, dict] = {}


def _core_readiness_payload(symbol: str, market_data_cfg: dict) -> dict:
    core_timeframes_raw = market_data_cfg.get("regime_core_timeframes", list(DEFAULT_REGIME_CORE_TIMEFRAMES))
    core_timeframes: list[str] = []
    if isinstance(core_timeframes_raw, list):
        for item in core_timeframes_raw:
            tf = str(item or "").strip().lower()
            if tf and tf not in core_timeframes:
                core_timeframes.append(tf)
    if not core_timeframes:
        core_timeframes = list(DEFAULT_REGIME_CORE_TIMEFRAMES)

    by_timeframe: dict[str, dict] = {}
    supported = {}
    stale = {}
    counts = {}
    mins = {}
    fresh = {}
    for tf in core_timeframes:
        min_required = int(market_data_cfg.get(f"regime_min_candles_{tf}", DEFAULT_REGIME_MIN_CANDLES.get(tf, 120)))
        stale_after_seconds = int(
            market_data_cfg.get(
                f"regime_stale_after_seconds_{tf}",
                DEFAULT_REGIME_STALE_AFTER_SECONDS.get(tf, 7200),
            )
        )
        try:
            meta = get_candle_meta(symbol=symbol, timeframe=tf, stale_after_seconds=stale_after_seconds)
        except Exception:
            meta = {
                "supported": False,
                "stale": True,
                "candle_count": 0,
                "status": "UNSUPPORTED_WINDOW",
                "reason": "meta_fetch_failed",
            }
        count = int(meta.get("candle_count") or 0)
        is_supported = bool(meta.get("supported", False))
        is_stale = bool(meta.get("stale", True))
        is_fresh = (not is_stale) and is_supported and count >= max(min_required, 1)
        supported[tf] = is_supported
        stale[tf] = is_stale
        counts[tf] = count
        mins[tf] = max(min_required, 1)
        fresh[tf] = is_fresh
        by_timeframe[tf] = {
            "supported": is_supported,
            "stale": is_stale,
            "candle_count": count,
            "min_required": max(min_required, 1),
            "status": meta.get("status"),
            "reason": meta.get("reason"),
            "last_update_ts": meta.get("last_update_ts"),
        }

    ready = all(bool(fresh.get(tf, False)) for tf in core_timeframes)
    reason = "ok"
    if not ready:
        missing = []
        for tf in core_timeframes:
            row = by_timeframe.get(tf, {})
            if not row.get("supported", False):
                missing.append(f"{tf}:unsupported")
            elif row.get("stale", True):
                missing.append(f"{tf}:stale")
            elif int(row.get("candle_count") or 0) < int(row.get("min_required") or 1):
                missing.append(f"{tf}:insufficient_depth")
        reason = ",".join(missing) if missing else "unknown"

    return {
        "timeframes": core_timeframes,
        "ready": ready,
        "reason": reason,
        "by_timeframe": by_timeframe,
        "supported_by_timeframe": supported,
        "stale_by_timeframe": stale,
        "counts_by_timeframe": counts,
        "min_counts_by_timeframe": mins,
        "fresh_by_timeframe": fresh,
    }


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


def _indicator_cache_key(symbol: str, timeframe: str) -> str:
    return f"{str(symbol).strip().upper()}:{str(timeframe).strip().lower()}"


def _build_indicator_features(
    prices: list[float],
    weights: list[float],
    *,
    atr_floor: float,
) -> dict:
    deltas = [
        abs(prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(1, len(prices))
        if prices[i - 1] > 0
    ]
    atr_raw = statistics.median(deltas) if deltas else 0.0
    atr = max(atr_raw, atr_floor)
    vwap = _weighted_average(prices, weights)
    median_price = statistics.median(prices)
    rsi = calculate_rsi(prices, period=14)
    ema_50 = _ema(prices[-100:], 50)
    ema_200 = _ema(prices[-250:], 200)
    ema_50_prev = _ema(prices[-101:-1], 50) if len(prices) > 101 else None
    ema_50_slope = None
    if ema_50 is not None and ema_50_prev is not None:
        ema_50_slope = ema_50 - ema_50_prev
    return {
        "first_price": prices[0],
        "atr_raw": atr_raw,
        "atr": atr,
        "vwap": vwap,
        "median_price": median_price,
        "rsi": rsi,
        "ema_50": ema_50,
        "ema_200": ema_200,
        "ema_50_slope": ema_50_slope,
        "high_24h": max(prices),
        "low_24h": min(prices),
        "history_points": len(prices),
        "recent_prices": prices[-60:],
    }


def _resolve_indicator_features(
    *,
    symbol: str,
    timeframe: str,
    history_source: str,
    candle_meta: dict,
    prices: list[float],
    weights: list[float],
    atr_floor: float,
) -> dict:
    cache_key = _indicator_cache_key(symbol, timeframe)
    latest_open = None
    if isinstance(candle_meta, dict):
        latest_open = candle_meta.get("latest_open_time")
    if history_source != "sqlite_candles" or latest_open is None:
        return _build_indicator_features(prices, weights, atr_floor=atr_floor)

    cached = _INDICATOR_CACHE.get(cache_key)
    if isinstance(cached, dict):
        if int(cached.get("latest_open_time", -1)) == int(latest_open):
            return dict(cached.get("features", {}))

    features = _build_indicator_features(prices, weights, atr_floor=atr_floor)
    _INDICATOR_CACHE[cache_key] = {
        "latest_open_time": int(latest_open),
        "features": dict(features),
    }
    return features


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


def _load_candle_history(symbol: str, timeframe: str, limit: int) -> tuple[list[float], list[float], dict]:
    rows = get_candles(symbol=symbol, timeframe=timeframe, limit=limit)
    meta = get_candle_meta(symbol=symbol, timeframe=timeframe)
    prices: list[float] = []
    weights: list[float] = []
    for row in rows:
        try:
            close_px = float(row.get("close"))
        except (TypeError, ValueError):
            continue
        if close_px <= 0:
            continue
        volume_raw = row.get("volume")
        try:
            volume = float(volume_raw) if volume_raw is not None else 1.0
        except (TypeError, ValueError):
            volume = 1.0
        prices.append(close_px)
        weights.append(max(volume, 1.0))
    return prices, weights, meta if isinstance(meta, dict) else {}


def _maybe_sync_candles(symbol: str, timeframe: str, sync_interval_seconds: int) -> None:
    now = time.time()
    key = f"{symbol}:{timeframe}"
    last_run = _LAST_CANDLE_SYNC_AT.get(key, 0.0)
    if now - last_run < max(int(sync_interval_seconds), 1):
        return
    _LAST_CANDLE_SYNC_AT[key] = now
    try:
        sync_new_candles(symbol=symbol, timeframe=timeframe, include_partial=False)
    except Exception as exc:
        logger.debug(f"Candle sync skipped for {symbol} {timeframe}: {exc}")


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
        candle_timeframe = str(
            market_data_cfg.get("decision_candle_timeframe", DEFAULT_CANDLE_TIMEFRAME)
        ).strip().lower() or DEFAULT_CANDLE_TIMEFRAME
        candle_history_limit = max(
            min(int(market_data_cfg.get("decision_candle_limit", DEFAULT_CANDLE_HISTORY_LIMIT)), 50_000),
            50,
        )
        candle_sync_enabled = bool(
            market_data_cfg.get("decision_candle_sync_enabled", DEFAULT_CANDLE_SYNC_ENABLED)
        )
        candle_sync_interval_seconds = max(
            int(
                market_data_cfg.get(
                    "decision_candle_sync_interval_seconds",
                    DEFAULT_CANDLE_SYNC_INTERVAL_SECONDS,
                )
            ),
            1,
        )

        # High-frequency healthy event; keep available at DEBUG to reduce log churn.
        logger.debug(f"Fetching market snapshot for {symbol}")
        order_book = get_order_book(symbol)
        book = _extract_order_book_snapshot(order_book, symbol)
        if book is None:
            return None

        if candle_sync_enabled:
            _maybe_sync_candles(
                symbol=symbol,
                timeframe=candle_timeframe,
                sync_interval_seconds=candle_sync_interval_seconds,
            )

        history = _record_mark_price(
            symbol,
            book["timestamp"],
            book["mid_price"],
            book["depth_weight"],
            history_seconds,
        )

        stream_prices = [sample["price"] for sample in history]
        stream_weights = [sample["weight"] for sample in history]
        prices = list(stream_prices)
        weights = list(stream_weights)
        history_source = "order_book_stream"
        candle_meta = {}
        try:
            candle_prices, candle_weights, candle_meta = _load_candle_history(
                symbol=symbol,
                timeframe=candle_timeframe,
                limit=candle_history_limit,
            )
            if len(candle_prices) >= min_history_points:
                prices = candle_prices
                weights = candle_weights
                history_source = "sqlite_candles"
        except Exception as exc:
            logger.debug(f"Candle history unavailable for {symbol}: {exc}")

        if not prices:
            return None
        first_price = prices[0]
        last_price = book["mid_price"]

        quality_reasons = []
        if book["spread_bps"] > max_spread_bps:
            quality_reasons.append("spread_too_wide")

        if len(prices) < min_history_points:
            quality_reasons.append("warming_up_history")
        if history_source == "sqlite_candles":
            if candle_meta.get("stale") is True:
                quality_reasons.append("candle_history_stale")
            if candle_meta.get("supported") is False:
                quality_reasons.append("candle_timeframe_unsupported")

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

        features = _resolve_indicator_features(
            symbol=symbol,
            timeframe=candle_timeframe,
            history_source=history_source,
            candle_meta=candle_meta,
            prices=prices,
            weights=weights,
            atr_floor=atr_floor,
        )

        first_price = float(features.get("first_price", prices[0]))
        atr_raw = float(features.get("atr_raw", 0.0))
        atr = float(features.get("atr", atr_floor))
        vwap = float(features.get("vwap", last_price))
        median_price = float(features.get("median_price", prices[-1]))
        rsi = features.get("rsi")
        ema_50 = features.get("ema_50")
        ema_200 = features.get("ema_200")
        ema_50_slope = features.get("ema_50_slope")
        high_24h = float(features.get("high_24h", max(prices)))
        low_24h = float(features.get("low_24h", min(prices)))
        recent_prices = list(features.get("recent_prices", prices[-60:]))
        history_points = int(features.get("history_points", len(prices)))

        raw_momentum = (last_price - first_price) / (first_price + EPSILON)
        norm_momentum = raw_momentum / (atr + EPSILON)
        data_quality_ok = not quality_reasons
        data_quality_reason = ",".join(quality_reasons) if quality_reasons else "ok"
        data_quality_status = "GOOD"
        if len(prices) <= 0:
            data_quality_status = "INSUFFICIENT"
        elif "candle_timeframe_unsupported" in quality_reasons:
            data_quality_status = "UNSUPPORTED_WINDOW"
        elif "candle_history_stale" in quality_reasons:
            data_quality_status = "STALE"
        elif quality_reasons:
            data_quality_status = "PARTIAL"
        core_readiness = _core_readiness_payload(symbol=symbol, market_data_cfg=market_data_cfg)

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
            "history_source": history_source,
            "momentum_raw": raw_momentum,
            "momentum_norm": norm_momentum,
            "rsi": rsi,

            "atr": atr,
            "atr_raw": atr_raw,
            "volatility": atr,

            "vwap": vwap,
            "median_price": median_price,
            "high_24h": high_24h,
            "low_24h": low_24h,
            "trade_count": history_points if data_quality_ok else 0,
            "history_points": history_points,
            "recent_prices": recent_prices,
            "snapshot_ts_epoch": float(book["timestamp"]),
            "sampling_minutes": 1.0 if history_source == "sqlite_candles" else max(
                1.0,
                float(history_seconds) / max(float(len(prices)), 1.0) / 60.0,
            ),
            "candle_timeframe": candle_timeframe,
            "data_quality_ok": data_quality_ok,
            "data_quality_reason": data_quality_reason,
            "data_quality_status": data_quality_status,
            "core_candle_readiness": core_readiness,

            "ema_50": ema_50,
            "ema_200": ema_200,
            "ema_50_slope": ema_50_slope,
        }

        ema_50_log = f"{ema_50:.5f}" if ema_50 is not None else "NA"
        ema_200_log = f"{ema_200:.5f}" if ema_200 is not None else "NA"
        ema_50_slope_log = f"{ema_50_slope:.8f}" if ema_50_slope is not None else "NA"

        logger.info(
            f"SNAPSHOT {symbol} | "
            f"price={last_price:.5f} "
            f"bid={book['best_bid']:.5f} "
            f"ask={book['best_ask']:.5f} "
            f"spread_bps={book['spread_bps']:.2f} "
            f"mom_norm={norm_momentum:.3f} "
            f"rsi={(rsi if rsi is not None else 50.0):.2f} "
            f"atr_raw={atr_raw:.5f} "
            f"vwap={vwap:.5f} "
            f"points={len(prices)} "
            f"quality={data_quality_reason} "
            f"24h_low={low_24h:.5f} "
            f"24h_high={high_24h:.5f} "
            f"ema_50={ema_50_log} "
            f"ema_200={ema_200_log} "
            f"ema_50_slope={ema_50_slope_log}"
        )

        return snapshot

    except Exception as e:
        logger.exception(f"Market snapshot error for {symbol}: {e}")
        return None
