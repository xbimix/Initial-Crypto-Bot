import time
import math
import statistics

from api.revolut_order_book import get_order_book as _get_order_book_api
from api.revolut_trades import get_last_trades as _get_last_trades_api
from data.feature_engine import resolve_indicator_features
from data.ingestion import OrderBookUpdate, TradeUpdate, fetch_order_book_update, fetch_trade_updates
from data.market_quality_policy import resolve_freshness_policy
from data.market_models import NormalizedMarketSnapshot, StrategyEvalGate
from data.market_data_service import get_candle_meta, get_candles
from data.market_snapshot_errors import SnapshotFailure, failure_payload
from data.replay_persistence import append_replay_event
from data.revolut_incremental_sync import sync_new_candles
from data.state_store import MARKET_DATA_STATE_STORE
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
DEFAULT_HISTORY_SECONDS = SECONDS_24H
DEFAULT_MIN_HISTORY_POINTS = 8
DEFAULT_MAX_SPREAD_BPS = 150.0
DEFAULT_MAX_BOOK_TRADE_GAP_PCT = 0.02
DEFAULT_TRADE_CONFIRMATION_LIMIT = 100
DEFAULT_CANDLE_TIMEFRAME = "1m"
DEFAULT_CANDLE_HISTORY_LIMIT = 6_000
DEFAULT_CANDLE_SYNC_ENABLED = False
DEFAULT_CANDLE_SYNC_INTERVAL_SECONDS = 20
DEFAULT_DECISION_CANDLE_STALE_INTERVALS = 3
DEFAULT_DECISION_CANDLE_MIN_STALE_SECONDS = 300
DEFAULT_REGIME_CORE_TIMEFRAMES = ("1h", "4h", "1d")
DEFAULT_REGIME_MIN_CANDLES = {"1h": 300, "4h": 180, "1d": 120}
DEFAULT_REGIME_STALE_AFTER_SECONDS = {"1h": 7200, "4h": 28800, "1d": 172800}
DEFAULT_STRICT_STRATEGY_EVAL_GATE_ENABLED = True
DEFAULT_STRATEGY_EVAL_MAX_AGE_SECONDS = 20.0
DEFAULT_STRATEGY_EVAL_MIN_QUALITY_SCORE = 0.0
DEFAULT_STRATEGY_ALLOW_PARTIAL_PARTICIPATION = False

_STATE_STORE = MARKET_DATA_STATE_STORE
_LAST_CANDLE_SYNC_AT: dict[str, float] = {}
# Backward-compatible aliases for legacy tests/callers while the canonical
# cache/state lives in the centralized market state store.
_PRICE_HISTORY = _STATE_STORE.legacy_price_history
_INDICATOR_CACHE = _STATE_STORE.legacy_indicator_cache


def _to_float(value, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_order_book(symbol: str, cfg: dict | None = None):
    return _get_order_book_api(symbol, cfg=cfg)


def get_last_trades(symbol: str, limit: int):
    return _get_last_trades_api(symbol=symbol, limit=limit)


def _format_snapshot_price(value: float | int | None) -> str:
    if value is None:
        return "NA"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "NA"
    if not math.isfinite(numeric):
        return "NA"
    precision = 5 if abs(numeric) >= 1 else 8
    return f"{numeric:.{precision}f}"


def _get_candle_meta_compatible(
    *,
    symbol: str,
    timeframe: str,
    stale_after_seconds: int | None = None,
) -> dict:
    """
    Backward-compatible metadata fetch.

    Some legacy call sites/tests monkeypatch `get_candle_meta` with the older
    `(symbol, timeframe)` signature. Prefer the richer call first, and
    gracefully retry with the legacy signature when needed.
    """
    if stale_after_seconds is None:
        return get_candle_meta(symbol=symbol, timeframe=timeframe)
    try:
        return get_candle_meta(
            symbol=symbol,
            timeframe=timeframe,
            stale_after_seconds=stale_after_seconds,
        )
    except TypeError:
        return get_candle_meta(symbol=symbol, timeframe=timeframe)


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
            meta = _get_candle_meta_compatible(
                symbol=symbol,
                timeframe=tf,
                stale_after_seconds=stale_after_seconds,
            )
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


def _classify_market_quality(quality_reasons: list[str], history_points: int) -> tuple[bool, str, str, str]:
    data_quality_ok = not quality_reasons
    data_quality_reason = ",".join(quality_reasons) if quality_reasons else "ok"
    data_quality_status = "GOOD"
    quality_state = "TRADABLE"
    if history_points <= 0:
        data_quality_status = "INSUFFICIENT"
        quality_state = "UNSAFE"
    elif "candle_timeframe_unsupported" in quality_reasons:
        data_quality_status = "UNSUPPORTED_WINDOW"
        quality_state = "UNSAFE"
    elif "candle_history_stale" in quality_reasons:
        data_quality_status = "STALE"
        quality_state = "UNSAFE"
    elif quality_reasons:
        data_quality_status = "PARTIAL"
        quality_state = "DEGRADED"
    return data_quality_ok, data_quality_reason, data_quality_status, quality_state


def _resolve_candle_stale_after_seconds(
    *,
    candle_timeframe: str,
    market_data_cfg: dict,
) -> int:
    stale_intervals = int(
        market_data_cfg.get(
            "decision_candle_stale_intervals",
            DEFAULT_DECISION_CANDLE_STALE_INTERVALS,
        )
        or DEFAULT_DECISION_CANDLE_STALE_INTERVALS
    )
    min_stale_seconds = int(
        market_data_cfg.get(
            "decision_candle_min_stale_seconds",
            DEFAULT_DECISION_CANDLE_MIN_STALE_SECONDS,
        )
        or DEFAULT_DECISION_CANDLE_MIN_STALE_SECONDS
    )
    stale_intervals = max(stale_intervals, 1)
    min_stale_seconds = max(min_stale_seconds, 60)
    policy = resolve_freshness_policy(
        timeframe=candle_timeframe,
        stale_intervals=stale_intervals,
        min_stale_seconds=min_stale_seconds,
    )
    return int(policy.stale_after_seconds)


def _compute_quality_score(
    *,
    history_points: int,
    min_history_points: int,
    spread_bps: float,
    max_spread_bps: float,
    quality_reasons: list[str],
    core_ready: bool,
) -> tuple[float, dict]:
    score = 1.0
    components: dict[str, float | int | bool] = {
        "history_points": int(history_points),
        "min_history_points": int(max(min_history_points, 1)),
        "spread_bps": float(spread_bps),
        "max_spread_bps": float(max(max_spread_bps, 1.0)),
        "core_ready": bool(core_ready),
    }

    history_ratio = min(float(history_points) / float(max(min_history_points, 1)), 1.0)
    score -= (1.0 - history_ratio) * 0.25
    components["history_ratio"] = round(history_ratio, 4)

    spread_ratio = min(float(spread_bps) / float(max(max_spread_bps, 1.0)), 2.0)
    spread_penalty = min(spread_ratio * 0.15, 0.25)
    score -= spread_penalty
    components["spread_penalty"] = round(spread_penalty, 4)

    penalties = {
        "candle_history_stale": 0.35,
        "candle_timeframe_unsupported": 0.55,
        "warming_up_history": 0.20,
        "order_book_tape_mismatch": 0.15,
        "spread_too_wide": 0.20,
    }
    applied_penalty = 0.0
    for reason in quality_reasons:
        penalty = penalties.get(reason)
        if penalty is not None:
            score -= penalty
            applied_penalty += penalty
    components["reason_penalty"] = round(applied_penalty, 4)

    if not core_ready:
        score -= 0.20
        components["core_penalty"] = 0.20
    else:
        components["core_penalty"] = 0.0

    score = max(0.0, min(score, 1.0))
    components["score"] = round(score, 4)
    return score, components


def _resolve_strategy_data_quality_ok(
    *,
    data_quality_ok: bool,
    data_quality_status: str,
    data_quality_score: float,
    cfg: dict,
) -> tuple[bool, str | None]:
    if data_quality_ok:
        return True, None

    market_data_cfg = cfg.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        market_data_cfg = {}
    allow_partial = bool(
        market_data_cfg.get(
            "strategy_allow_partial_participation",
            DEFAULT_STRATEGY_ALLOW_PARTIAL_PARTICIPATION,
        )
    )
    if not allow_partial:
        return False, None

    status = str(data_quality_status or "").strip().upper()
    if status not in {"GOOD", "PARTIAL"}:
        return False, None

    min_quality_score = float(
        market_data_cfg.get(
            "strategy_eval_min_quality_score",
            DEFAULT_STRATEGY_EVAL_MIN_QUALITY_SCORE,
        )
        or DEFAULT_STRATEGY_EVAL_MIN_QUALITY_SCORE
    )
    # Keep this path intentionally conservative: participation by score-floor
    # is only active once an explicit, positive threshold is configured.
    if min_quality_score <= 0:
        return False, None

    if float(data_quality_score) < min_quality_score:
        return False, None
    return True, "partial_quality_score_floor"


def _build_strategy_eval_gate(snapshot: dict, cfg: dict) -> StrategyEvalGate:
    market_data_cfg = cfg.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        market_data_cfg = {}
    gate_enabled = bool(
        market_data_cfg.get(
            "strict_strategy_eval_gate_enabled",
            DEFAULT_STRICT_STRATEGY_EVAL_GATE_ENABLED,
        )
    )
    if not gate_enabled:
        return StrategyEvalGate(allowed=True)

    quality_status = str(snapshot.get("data_quality_status") or "UNKNOWN").upper()
    quality_state = str(snapshot.get("data_quality_state") or "UNKNOWN").upper()
    blocked_reason: str | None = None
    if quality_status in {"STALE", "INSUFFICIENT", "UNSUPPORTED_WINDOW"}:
        blocked_reason = f"market_data_quality:{quality_status.lower()}"

    core_ready = True
    readiness = snapshot.get("core_candle_readiness", {})
    if isinstance(readiness, dict):
        core_ready = bool(readiness.get("ready", True))
        if not core_ready and blocked_reason is None:
            blocked_reason = f"core_not_ready:{readiness.get('reason', 'unknown')}"

    snapshot_age_seconds: float | None = None
    snapshot_ts = snapshot.get("snapshot_ts_epoch")
    if snapshot_ts is not None:
        try:
            snapshot_age_seconds = max(0.0, time.time() - float(snapshot_ts))
        except (TypeError, ValueError):
            snapshot_age_seconds = None
    max_age_seconds = float(
        market_data_cfg.get(
            "strategy_eval_max_snapshot_age_seconds",
            DEFAULT_STRATEGY_EVAL_MAX_AGE_SECONDS,
        )
    )
    if (
        snapshot_age_seconds is not None
        and max_age_seconds > 0
        and snapshot_age_seconds > max_age_seconds
        and blocked_reason is None
    ):
        blocked_reason = "market_snapshot_stale"

    min_quality_score = float(
        market_data_cfg.get(
            "strategy_eval_min_quality_score",
            DEFAULT_STRATEGY_EVAL_MIN_QUALITY_SCORE,
        )
        or DEFAULT_STRATEGY_EVAL_MIN_QUALITY_SCORE
    )
    quality_score = _to_float(snapshot.get("data_quality_score"), None)
    if (
        quality_score is not None
        and min_quality_score > 0
        and quality_score < min_quality_score
        and blocked_reason is None
    ):
        blocked_reason = f"market_data_quality_score:{quality_score:.3f}<{min_quality_score:.3f}"

    return StrategyEvalGate(
        allowed=blocked_reason is None,
        blocked_reason=blocked_reason,
        snapshot_age_seconds=snapshot_age_seconds,
        quality_status=quality_status,
        quality_state=quality_state,
        quality_score=quality_score,
        core_ready=core_ready,
    )


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


def _extract_order_book_snapshot(update: OrderBookUpdate) -> dict | None:
    bids = list(update.bids)
    asks = list(update.asks)
    symbol = update.symbol
    if not bids or not asks:
        logger.warning(f"No valid order book levels for {symbol}")
        return None

    best_ask = min(asks, key=lambda level: level.price)
    best_bid = max(bids, key=lambda level: level.price)

    if best_ask.price <= best_bid.price:
        logger.warning(
            f"Crossed order book for {symbol}: "
            f"bid={best_bid.price:.5f} ask={best_ask.price:.5f}"
        )
        return None

    mid_price = (best_bid.price + best_ask.price) / 2
    spread = best_ask.price - best_bid.price
    spread_bps = (spread / (mid_price + EPSILON)) * 10000

    top_bid_size = best_bid.size
    top_ask_size = best_ask.size
    microprice = (
        ((best_ask.price * top_bid_size) + (best_bid.price * top_ask_size))
        / (top_bid_size + top_ask_size + EPSILON)
    )

    total_bid_depth = sum(level.size for level in bids)
    total_ask_depth = sum(level.size for level in asks)
    depth_weight = total_bid_depth + total_ask_depth

    snapshot_ts = (
        update.source.exchange_ts_epoch
        or best_ask.ts_epoch
        or best_bid.ts_epoch
        or update.source.received_ts_epoch
        or time.time()
    )

    return {
        "best_bid": best_bid.price,
        "best_ask": best_ask.price,
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
    limit: int,
    max_trade_jump_pct: float,
) -> tuple[list[dict], int]:
    trades = fetch_trade_updates(symbol, limit=limit, fetcher=get_last_trades)
    parsed = [
        {"price": float(item.price), "ts": float(item.ts_epoch), "size": float(item.size)}
        for item in trades
        if isinstance(item, TradeUpdate)
    ]
    parsed.sort(key=lambda item: float(item["ts"]))
    return _filter_price_jumps(parsed, max_trade_jump_pct)


def _record_mark_price(
    symbol: str,
    snapshot_ts: float,
    mark_price: float,
    weight: float,
    history_seconds: int,
) -> tuple[list[dict], int]:
    result = _STATE_STORE.record_mark_price(
        symbol=symbol,
        snapshot_ts=snapshot_ts,
        mark_price=mark_price,
        weight=weight,
        history_seconds=history_seconds,
    )
    return result.history, result.history_version


def _load_candle_history(symbol: str, timeframe: str, limit: int, meta: dict) -> tuple[list[float], list[float], dict, int]:
    latest_open = None
    if isinstance(meta, dict):
        latest_open = meta.get("latest_open_time")
    cached = _STATE_STORE.get_candle_cache(symbol=symbol, timeframe=timeframe)
    if (
        cached is not None
        and cached.latest_open_time is not None
        and latest_open is not None
        and int(cached.latest_open_time) == int(latest_open)
        and len(cached.prices) >= 1
    ):
        return list(cached.prices[-limit:]), list(cached.weights[-limit:]), meta, int(cached.version)

    rows = get_candles(symbol=symbol, timeframe=timeframe, limit=limit)
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

    refreshed = _STATE_STORE.set_candle_cache(
        symbol=symbol,
        timeframe=timeframe,
        latest_open_time=int(latest_open) if latest_open is not None else None,
        prices=prices,
        weights=weights,
        metadata=meta if isinstance(meta, dict) else {},
        refreshed_at_epoch=time.time(),
    )
    return prices, weights, meta if isinstance(meta, dict) else {}, int(refreshed.version)


def _maybe_sync_candles(
    symbol: str,
    timeframe: str,
    sync_interval_seconds: int,
    *,
    cfg: dict | None = None,
) -> None:
    now = time.time()
    key = f"{symbol}:{timeframe}"
    last_run = _LAST_CANDLE_SYNC_AT.get(key, 0.0)
    if now - last_run < max(int(sync_interval_seconds), 1):
        return
    _LAST_CANDLE_SYNC_AT[key] = now
    try:
        sync_new_candles(
            symbol=symbol,
            timeframe=timeframe,
            include_partial=False,
            cfg=cfg,
        )
    except Exception as exc:
        logger.debug(f"Candle sync skipped for {symbol} {timeframe}: {exc}")


def _raise_snapshot_failure(
    *,
    symbol: str,
    code: str,
    stage: str,
    message: str,
    details: dict | None = None,
) -> None:
    raise SnapshotFailure(
        symbol=str(symbol or "").strip().upper(),
        code=str(code or "").strip().lower(),
        stage=str(stage or "").strip().lower(),
        message=str(message or "").strip(),
        details=dict(details or {}),
    )


def _log_snapshot_failure(failure: SnapshotFailure, cfg: dict | None) -> None:
    payload = failure_payload(failure)
    logger.warning(
        "Market snapshot blocked | symbol=%s code=%s stage=%s message=%s details=%s",
        payload.get("symbol"),
        payload.get("code"),
        payload.get("stage"),
        payload.get("message"),
        payload.get("details"),
    )
    append_replay_event("market_snapshot_failure", payload, cfg)


def fetch_market_snapshot(symbol: str, cfg: dict) -> dict | None:
    try:
        lookback = cfg.get("lookback", 200)
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
        candle_stale_after_seconds = _resolve_candle_stale_after_seconds(
            candle_timeframe=candle_timeframe,
            market_data_cfg=market_data_cfg,
        )
        candle_sync_enabled = bool(
            market_data_cfg.get("decision_candle_sync_enabled", DEFAULT_CANDLE_SYNC_ENABLED)
        )
        incremental_sync_enabled = bool(
            market_data_cfg.get("incremental_sync_enabled", True)
        )
        allow_concurrent_decision_sync = bool(
            market_data_cfg.get("decision_candle_allow_concurrent_sync", False)
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
        try:
            order_book_update = fetch_order_book_update(symbol, cfg=cfg, fetcher=get_order_book)
        except Exception as exc:
            _raise_snapshot_failure(
                symbol=symbol,
                code="order_book_fetch_error",
                stage="ingestion_order_book",
                message=str(exc),
            )
        if order_book_update is None:
            _raise_snapshot_failure(
                symbol=symbol,
                code="order_book_empty",
                stage="ingestion_order_book",
                message="order_book_update_missing",
            )
        append_replay_event(
            "normalized_order_book",
            {
                "symbol": order_book_update.symbol,
                "bids": len(order_book_update.bids),
                "asks": len(order_book_update.asks),
                "received_ts_epoch": order_book_update.source.received_ts_epoch,
                "exchange_ts_epoch": order_book_update.source.exchange_ts_epoch,
                "source": order_book_update.source.source,
            },
            cfg,
        )
        try:
            book = _extract_order_book_snapshot(order_book_update)
        except Exception as exc:
            _raise_snapshot_failure(
                symbol=symbol,
                code="order_book_snapshot_parse_error",
                stage="normalize_order_book",
                message=str(exc),
            )
        if book is None:
            _raise_snapshot_failure(
                symbol=symbol,
                code="order_book_invalid",
                stage="normalize_order_book",
                message="order_book_snapshot_unusable",
            )

        should_run_local_decision_sync = bool(
            candle_sync_enabled
            and (
                not incremental_sync_enabled
                or allow_concurrent_decision_sync
            )
        )
        if should_run_local_decision_sync:
            _maybe_sync_candles(
                symbol=symbol,
                timeframe=candle_timeframe,
                sync_interval_seconds=candle_sync_interval_seconds,
                cfg=cfg,
            )

        try:
            history, history_version = _record_mark_price(
                symbol,
                book["timestamp"],
                book["mid_price"],
                book["depth_weight"],
                history_seconds,
            )
        except Exception as exc:
            _raise_snapshot_failure(
                symbol=symbol,
                code="mark_price_record_error",
                stage="state_store_mark_price",
                message=str(exc),
            )

        stream_prices = [sample["price"] for sample in history]
        stream_weights = [sample["weight"] for sample in history]
        prices = list(stream_prices)
        weights = list(stream_weights)
        history_source = "order_book_stream"
        candle_meta = {}
        indicator_history_version = int(history_version or 0)
        try:
            candle_meta = _get_candle_meta_compatible(
                symbol=symbol,
                timeframe=candle_timeframe,
                stale_after_seconds=candle_stale_after_seconds,
            )
            candle_prices, candle_weights, candle_meta, candle_history_version = _load_candle_history(
                symbol=symbol,
                timeframe=candle_timeframe,
                limit=candle_history_limit,
                meta=candle_meta if isinstance(candle_meta, dict) else {},
            )
            if len(candle_prices) >= min_history_points:
                prices = candle_prices
                weights = candle_weights
                history_source = "sqlite_candles"
                latest_open = candle_meta.get("latest_open_time") if isinstance(candle_meta, dict) else None
                indicator_history_version = int(latest_open) if latest_open is not None else int(candle_history_version or 0)
        except Exception as exc:
            logger.debug(f"Candle history unavailable for {symbol}: {exc}")

        if not prices:
            _raise_snapshot_failure(
                symbol=symbol,
                code="price_history_empty",
                stage="history_selection",
                message="no_prices_after_history_selection",
                details={"history_source": history_source},
            )
        first_price = prices[0]
        last_price = book["mid_price"]
        snapshot_ts_epoch = float(book["timestamp"])

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
                limit=trade_confirmation_limit,
                max_trade_jump_pct=max_trade_jump_pct,
            )
            if filtered_trades:
                append_replay_event(
                    "normalized_trades",
                    {
                        "symbol": symbol,
                        "count": len(filtered_trades),
                        "latest_trade_price": filtered_trades[-1]["price"],
                        "latest_trade_ts_epoch": filtered_trades[-1]["ts"],
                    },
                    cfg,
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

        latest_open = candle_meta.get("latest_open_time") if isinstance(candle_meta, dict) else None
        candle_last_update_ts = None
        candle_age_seconds = None
        candle_age_over_stale_ratio = None
        if history_source == "sqlite_candles" and isinstance(candle_meta, dict):
            candle_last_update_ts = candle_meta.get("last_update_ts")
            try:
                meta_age = _to_float(candle_meta.get("age_seconds"), None)
                if meta_age is not None:
                    candle_age_seconds = max(float(meta_age), 0.0)
                elif candle_last_update_ts is not None:
                    # Backward-compatible fallback for older metadata payloads.
                    candle_age_seconds = max(
                        0.0,
                        time.time() - (float(candle_last_update_ts) / 1000.0),
                    )
                if candle_age_seconds is not None and candle_stale_after_seconds > 0:
                    candle_age_over_stale_ratio = candle_age_seconds / float(candle_stale_after_seconds)
            except (TypeError, ValueError):
                candle_age_seconds = None
                candle_age_over_stale_ratio = None

        feature_result = resolve_indicator_features(
            store=_STATE_STORE,
            symbol=symbol,
            timeframe=candle_timeframe,
            history_source=history_source,
            history_version=indicator_history_version,
            latest_open_time=int(latest_open) if latest_open is not None else None,
            prices=prices,
            weights=weights,
            atr_floor=atr_floor,
            rsi_fn=calculate_rsi,
        )
        features = feature_result.features

        first_price = float(features.get("first_price", prices[0]))
        atr_raw = float(features.get("atr_raw", 0.0))
        atr = float(features.get("atr", atr_floor))
        # Robust fallback when close-to-close movement is quantized/flat but
        # candle high/low ranges still carry volatility information.
        if atr_raw <= 0.0 and history_source == "sqlite_candles":
            try:
                candle_rows = get_candles(
                    symbol=symbol,
                    timeframe=candle_timeframe,
                    limit=min(candle_history_limit, 600),
                )
            except Exception:
                candle_rows = []
            range_pcts: list[float] = []
            if isinstance(candle_rows, list):
                for row in candle_rows:
                    if not isinstance(row, dict):
                        continue
                    high = _to_float(row.get("high"), None)
                    low = _to_float(row.get("low"), None)
                    close_px = _to_float(row.get("close"), None)
                    if (
                        high is None
                        or low is None
                        or close_px is None
                        or close_px <= 0
                        or high < low
                    ):
                        continue
                    pct = max((high - low) / close_px, 0.0)
                    if pct > 0.0:
                        range_pcts.append(pct)
            if range_pcts:
                atr_raw = float(statistics.median(range_pcts))
                atr = max(atr_raw, float(atr_floor))
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
        sampling_minutes = (
            1.0
            if history_source == "sqlite_candles"
            else max(
                1.0,
                float(history_seconds) / max(float(len(prices)), 1.0) / 60.0,
            )
        )
        # Regime routing needs >=24h depth while route-scoring uses short context.
        regime_required_points = max(int(round((24.0 * 60.0) / max(sampling_minutes, 1.0))), 60)
        regime_recent_prices = list(prices[-min(len(prices), regime_required_points):])

        raw_momentum = (last_price - first_price) / (first_price + EPSILON)
        norm_momentum = raw_momentum / (atr + EPSILON)
        data_quality_ok, data_quality_reason, data_quality_status, quality_state = _classify_market_quality(
            quality_reasons=quality_reasons,
            history_points=history_points,
        )
        core_readiness = _core_readiness_payload(symbol=symbol, market_data_cfg=market_data_cfg)
        data_quality_score, data_quality_components = _compute_quality_score(
            history_points=history_points,
            min_history_points=min_history_points,
            spread_bps=book["spread_bps"],
            max_spread_bps=max_spread_bps,
            quality_reasons=quality_reasons,
            core_ready=bool(core_readiness.get("ready", True)),
        )
        strategy_quality_ok, strategy_quality_mode = _resolve_strategy_data_quality_ok(
            data_quality_ok=data_quality_ok,
            data_quality_status=data_quality_status,
            data_quality_score=data_quality_score,
            cfg=cfg,
        )
        if not bool(core_readiness.get("ready", True)) and quality_state == "TRADABLE":
            quality_state = "DEGRADED"

        snapshot_payload = {
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
            "atr_pct": atr_raw,
            "volatility": atr,

            "vwap": vwap,
            "median_price": median_price,
            "high_24h": high_24h,
            "low_24h": low_24h,
            "trade_count": history_points if strategy_quality_ok else 0,
            "history_points": history_points,
            "recent_prices": recent_prices,
            "regime_recent_prices": regime_recent_prices,
            "regime_recent_prices_points": len(regime_recent_prices),
            "snapshot_ts_epoch": snapshot_ts_epoch,
            "sampling_minutes": sampling_minutes,
            "candle_timeframe": candle_timeframe,
            "candle_last_update_ts": candle_last_update_ts,
            "candle_age_seconds": candle_age_seconds,
            "candle_stale_after_seconds": float(candle_stale_after_seconds),
            "candle_age_over_stale_ratio": candle_age_over_stale_ratio,
            "data_quality_ok": strategy_quality_ok,
            "data_quality_base_ok": data_quality_ok,
            "data_quality_participation_mode": strategy_quality_mode or "strict",
            "data_quality_reason": data_quality_reason,
            "data_quality_status": data_quality_status,
            "data_quality_score": data_quality_score,
            "data_quality_components": data_quality_components,
            "core_candle_readiness": core_readiness,

            "ema_50": ema_50,
            "ema_200": ema_200,
            "ema_50_slope": ema_50_slope,
        }
        merge = _STATE_STORE.merge_snapshot_fields(
            symbol=symbol,
            fields=snapshot_payload,
            snapshot_ts_epoch=float(book["timestamp"]),
            quality_state=quality_state,
        )
        append_replay_event(
            "market_snapshot_change",
            {
                "symbol": symbol,
                "snapshot_version": merge.version,
                "state_changed": merge.state_changed,
                "changed_fields": list(merge.changed_fields),
                "quality_state": merge.quality_state,
            },
            cfg,
        )
        normalized = NormalizedMarketSnapshot.from_payload(
            snapshot_payload,
            snapshot_version=merge.version,
            field_timestamps=merge.field_timestamps,
            quality_state=merge.quality_state,
        )
        gate = _build_strategy_eval_gate(normalized.to_legacy_dict(), cfg)
        normalized = NormalizedMarketSnapshot.from_payload(
            snapshot_payload,
            snapshot_version=merge.version,
            field_timestamps=merge.field_timestamps,
            quality_state=merge.quality_state,
            strategy_eval_gate=gate,
        )
        snapshot = normalized.to_legacy_dict()

        ema_50_log = _format_snapshot_price(ema_50)
        ema_200_log = _format_snapshot_price(ema_200)
        ema_50_slope_log = f"{ema_50_slope:.8f}" if ema_50_slope is not None else "NA"

        logger.info(
            f"SNAPSHOT {symbol} | "
            f"price={_format_snapshot_price(last_price)} "
            f"bid={_format_snapshot_price(book['best_bid'])} "
            f"ask={_format_snapshot_price(book['best_ask'])} "
            f"spread_bps={book['spread_bps']:.2f} "
            f"mom_norm={norm_momentum:.3f} "
            f"rsi={(rsi if rsi is not None else 50.0):.2f} "
            f"atr_raw={_format_snapshot_price(atr_raw)} "
            f"vwap={_format_snapshot_price(vwap)} "
            f"points={len(prices)} "
            f"quality={data_quality_reason} "
            f"24h_low={_format_snapshot_price(low_24h)} "
            f"24h_high={_format_snapshot_price(high_24h)} "
            f"ema_50={ema_50_log} "
            f"ema_200={ema_200_log} "
            f"ema_50_slope={ema_50_slope_log}"
        )

        return snapshot

    except SnapshotFailure as failure:
        _log_snapshot_failure(failure, cfg)
        return None
    except Exception as e:
        logger.exception(f"Market snapshot error for {symbol}: {e}")
        append_replay_event(
            "market_snapshot_failure",
            {
                "symbol": str(symbol or "").strip().upper(),
                "code": "unexpected_exception",
                "stage": "fetch_market_snapshot",
                "message": str(e),
            },
            cfg,
        )
        return None
