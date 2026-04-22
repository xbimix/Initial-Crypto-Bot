from __future__ import annotations

from collections.abc import Callable
from typing import Any


def status_payload(
    *,
    load_config: Callable[[], dict],
    normalize_symbols: Callable[[Any], list[str]],
    parse_enabled_map: Callable[[Any], dict],
    parse_token_regime_map: Callable[[Any], dict],
    is_enabled: Callable[[dict, str], bool],
) -> dict:
    cfg = load_config()

    symbols = normalize_symbols(cfg.get("symbols", []))
    symbol_buy_enabled = parse_enabled_map(cfg.get("symbol_buy_enabled", {}))
    symbol_sell_enabled = parse_enabled_map(cfg.get("symbol_sell_enabled", {}))
    token_regimes = parse_token_regime_map(cfg.get("token_regimes", {}))

    buy_enabled_symbols = [
        symbol
        for symbol in symbols
        if is_enabled(symbol_buy_enabled, symbol)
    ]
    sell_enabled_symbols = [
        symbol
        for symbol in symbols
        if is_enabled(symbol_sell_enabled, symbol)
    ]

    risk = cfg.get("risk", {})
    if not isinstance(risk, dict):
        risk = {}
    trade_window = risk.get("trade_window_utc", {})
    if not isinstance(trade_window, dict):
        trade_window = {}
    symbol_cooldown = risk.get("symbol_cooldown_seconds", {})
    if not isinstance(symbol_cooldown, dict):
        symbol_cooldown = {}

    return {
        "enabled": bool(cfg.get("enabled", False)),
        "trading_enabled": bool(cfg.get("trading_enabled", False)),
        "emergency_stop": bool(cfg.get("emergency_stop", False)),
        "execution_mode": cfg.get("execution_mode"),
        "symbols": symbols,
        "token_regimes": token_regimes,
        "buy_enabled_symbols": buy_enabled_symbols,
        "sell_enabled_symbols": sell_enabled_symbols,
        "loop_sleep": cfg.get("loop_sleep"),
        "cooldown_seconds": risk.get("cooldown_seconds"),
        "max_concurrent_trades": risk.get("max_concurrent_trades"),
        "max_concurrent_trades_per_token": risk.get(
            "max_concurrent_trades_per_token"
        ),
        "max_trade_amount_usd": risk.get("max_trade_amount_usd"),
        "trade_amount_usd": risk.get("trade_amount_usd"),
        "max_portfolio_exposure_pct": risk.get("max_portfolio_exposure_pct"),
        "max_exposure_per_token_pct": risk.get("max_exposure_per_token_pct"),
        "daily_loss_limit_usd": risk.get("daily_loss_limit_usd"),
        "daily_loss_auto_pause": risk.get("daily_loss_auto_pause"),
        "daily_loss_close_all": risk.get("daily_loss_close_all"),
        "signal_confirmation_cycles": risk.get("signal_confirmation_cycles"),
        "trade_window_utc": trade_window,
        "symbol_cooldown_seconds": symbol_cooldown,
    }


def health_payload(*, now_utc_iso: Callable[[], str]) -> dict:
    return {
        "status": "ok",
        "service": "control",
        "time": now_utc_iso(),
    }


def revolut_account_payload(
    *,
    force: bool,
    sync_account_snapshot: Callable[[], dict],
    read_account_snapshot: Callable[..., dict],
) -> dict:
    if force:
        return sync_account_snapshot()
    snapshot = read_account_snapshot(default={})
    if not snapshot:
        snapshot = sync_account_snapshot()
    return snapshot


def revolut_universe_payload(
    *,
    force: bool,
    load_config: Callable[[], dict],
    get_universe_snapshot: Callable[..., dict],
) -> dict:
    cfg = load_config()
    return get_universe_snapshot(cfg, force_refresh=force)


def market_data_candles_payload(
    *,
    symbol: str,
    timeframe: str,
    limit: int,
    get_candles: Callable[..., list[dict]],
    get_candle_meta: Callable[..., dict],
) -> dict:
    rows = get_candles(symbol=symbol, timeframe=timeframe, limit=limit)
    meta = get_candle_meta(symbol=symbol, timeframe=timeframe)

    points = []
    for row in rows:
        try:
            ts_epoch = int(row.get("open_time")) / 1000.0
            close = float(row.get("close"))
        except (TypeError, ValueError):
            continue
        if ts_epoch <= 0 or close <= 0:
            continue
        points.append({"tsEpoch": ts_epoch, "price": close})

    return {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        "limit": limit,
        "rows": rows,
        "points": points,
        "meta": meta,
    }


def market_data_candles_batch_payload(
    *,
    symbols: list[str],
    timeframe: str,
    limit: int,
    get_candles: Callable[..., list[dict]],
    get_candle_meta: Callable[..., dict],
    logger,
) -> dict:
    payload: dict[str, dict] = {}
    for symbol in symbols[:80]:
        try:
            rows = get_candles(symbol=symbol, timeframe=timeframe, limit=limit)
            meta = get_candle_meta(symbol=symbol, timeframe=timeframe)
        except Exception as exc:
            logger.exception(f"market-data candle batch failed for {symbol} {timeframe}: {exc}")
            payload[symbol] = {
                "status": "error",
                "points": [],
                "meta": {"supported": False, "stale": True, "reason": "backend_exception"},
            }
            continue

        points = []
        for row in rows:
            try:
                ts_epoch = int(row.get("open_time")) / 1000.0
                close = float(row.get("close"))
            except (TypeError, ValueError):
                continue
            if ts_epoch <= 0 or close <= 0:
                continue
            points.append({"tsEpoch": ts_epoch, "price": close})

        latest = points[-1] if points else None
        payload[symbol] = {
            "status": "ok",
            "points": points,
            "latest": latest,
            "meta": meta,
        }

    return {
        "status": "ok",
        "timeframe": timeframe,
        "limit": limit,
        "symbols": payload,
    }


def orderbook_top5_payload(
    *,
    symbol: str,
    get_orderbook_top5: Callable[..., dict],
) -> dict:
    payload = get_orderbook_top5(symbol=symbol)
    return {"status": "ok", "symbol": symbol, "orderbook": payload}


def route_quality_payload(
    *,
    load_config: Callable[[], dict],
    load_route_quality_report_cached: Callable[..., dict],
    state_dir,
) -> dict:
    cfg = load_config()
    payload = load_route_quality_report_cached(
        state_dir=state_dir,
        cfg=cfg if isinstance(cfg, dict) else {},
    )
    return {"status": "ok", "route_quality": payload}


def ready_payload(*, refresh_startup_status: Callable[[], dict]) -> tuple[dict, int]:
    status_payload_obj = refresh_startup_status()
    if status_payload_obj.get("ok"):
        payload = dict(status_payload_obj)
        payload["status"] = "ok"
        return payload, 200
    payload = dict(status_payload_obj)
    payload["status"] = "error"
    payload["error"] = "startup_checks_failed"
    payload["code"] = "not_ready"
    return payload, 503
