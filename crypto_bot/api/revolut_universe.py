from __future__ import annotations

import time
from pathlib import Path

from api.revolut_api import _get
from data.market_data import fetch_market_snapshot
from strategy.regime import detect_regime
from utils.logger import setup_logger
from utils.state_io import read_json_file, write_json_file

logger = setup_logger("revolut_universe")

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
UNIVERSE_SNAPSHOT_PATH = STATE_DIR / "revolut_universe_snapshot.json"
UNIVERSE_PRICE_HISTORY_PATH = STATE_DIR / "revolut_universe_price_history.json"
DEFAULT_UNIVERSE_TTL_SECONDS = 60.0
DEFAULT_ALLOWED_QUOTES = {"USD", "USDT", "USDC"}
# Keep default at zero to avoid heavy advisory sync load affecting runtime loops.
DEFAULT_ENRICHED_SNAPSHOT_LIMIT = 0
SECONDS_24H = 86400.0
PRICE_HISTORY_RETENTION_SECONDS = 36 * 3600.0
MAX_PRICE_HISTORY_POINTS_PER_SYMBOL = 512


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_symbol(raw) -> str:
    if not isinstance(raw, str):
        return ""
    token = raw.strip().upper()
    if not token:
        return ""
    token = token.replace("/", "-").replace("_", "-")
    parts = [p for p in token.split("-") if p]
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    return token


def _extract_base_quote(row: dict, symbol: str) -> tuple[str, str]:
    base = ""
    quote = ""
    for key in ("base", "base_asset", "baseCurrency", "base_currency", "base_ccy", "aid"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            base = value.strip().upper()
            break
    for key in ("quote", "quote_asset", "quoteCurrency", "quote_currency", "quote_ccy", "pc"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            quote = value.strip().upper()
            break
    if not base or not quote:
        parts = symbol.split("-", 1)
        if len(parts) == 2:
            base = base or parts[0]
            quote = quote or parts[1]
    return base, quote


def _is_active_row(row: dict) -> bool:
    status_fields = (
        row.get("status"),
        row.get("state"),
        row.get("trading_status"),
    )
    for status in status_fields:
        if isinstance(status, str):
            normalized = status.strip().upper()
            if normalized in {"INACTIVE", "DISABLED", "SUSPENDED", "HALTED"}:
                return False
            if normalized in {"ACTIVE", "TRADING", "ENABLED", "OPEN"}:
                return True

    for key in ("active", "enabled", "tradable", "spot_trading_allowed", "is_tradable"):
        value = row.get(key)
        if isinstance(value, bool):
            if value is False:
                return False
            if value is True:
                return True

    return True


def _extract_instrument_rows(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("instruments", "pairs", "symbols"):
            nested = data.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


def _extract_symbol_from_trade_row(row: dict) -> str:
    aid = str(row.get("aid", "")).strip().upper()
    quote = str(row.get("pc", "")).strip().upper()
    if aid and quote:
        return f"{aid}-{quote}"
    return ""


def _extract_ticker_price(row: dict) -> float | None:
    for key in ("mid", "last_price", "ask", "bid", "price"):
        value = _to_float(row.get(key), default=0.0)
        if value > 0:
            return value
    return None


def _normalize_price_history_entries(raw_entries: object, cutoff_ts: float) -> list[dict]:
    if not isinstance(raw_entries, list):
        return []
    parsed = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        ts = _to_float(item.get("ts"), default=0.0)
        price = _to_float(item.get("price"), default=0.0)
        if ts <= 0 or price <= 0 or ts < cutoff_ts:
            continue
        parsed.append({"ts": ts, "price": price})
    parsed.sort(key=lambda sample: sample["ts"])
    return parsed


def _load_price_history_map() -> dict:
    raw = read_json_file(UNIVERSE_PRICE_HISTORY_PATH, default={}, strict=False)
    if not isinstance(raw, dict):
        return {}
    return raw


def _append_price_history_sample(
    symbol: str,
    current_price: float | None,
    now_ts: float,
    previous_history: dict,
) -> list[dict]:
    cutoff_ts = now_ts - PRICE_HISTORY_RETENTION_SECONDS
    entries = _normalize_price_history_entries(previous_history.get(symbol), cutoff_ts)
    if current_price is None or current_price <= 0:
        return entries

    if not entries or abs(entries[-1]["ts"] - now_ts) > 1:
        entries.append(
            {
                "ts": now_ts,
                "price": float(current_price),
            }
        )
    else:
        entries[-1] = {"ts": now_ts, "price": float(current_price)}

    entries = [sample for sample in entries if sample["ts"] >= cutoff_ts]
    if len(entries) > MAX_PRICE_HISTORY_POINTS_PER_SYMBOL:
        entries = entries[-MAX_PRICE_HISTORY_POINTS_PER_SYMBOL:]
    return entries


def _compute_change_24h_pct(entries: list[dict], now_ts: float, current_price: float | None) -> float | None:
    if current_price is None or current_price <= 0 or not entries:
        return None
    target_ts = now_ts - SECONDS_24H
    baseline = None
    for sample in entries:
        if sample["ts"] <= target_ts:
            baseline = sample["price"]
        else:
            break
    if baseline is None or baseline <= 0:
        return None
    return ((float(current_price) - baseline) / baseline) * 100.0


def _build_rows_from_trade_tape() -> tuple[list[dict], str]:
    payload = _get("/public/last-trades", params={"limit": 100}, auth=False)
    trades = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(trades, list):
        return [], "source=/public/last-trades(empty)"

    seen = set()
    rows = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        symbol = _extract_symbol_from_trade_row(trade)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        rows.append({"symbol": symbol, "status": "TRADING"})

    return rows, "source=/public/last-trades"


def _fetch_revolut_instruments() -> tuple[list[dict], list[str]]:
    reasons = []
    # Revolut X currently exposes broad tradable pair coverage through /tickers.
    for path in ("/tickers", "/configuration/currencies", "/instruments", "/pairs", "/assets"):
        try:
            payload = _get(path, auth=True)
            rows = _extract_instrument_rows(payload)
            if rows:
                reasons.append(f"source={path}")
                return rows, reasons
            reasons.append(f"{path}:empty")
        except Exception as exc:
            reasons.append(f"{path}:{exc}")

    # Last fallback: build a lightweight universe from the public trade tape.
    try:
        tape_rows, source = _build_rows_from_trade_tape()
        if tape_rows:
            reasons.append(source)
            return tape_rows, reasons
        reasons.append(f"{source}:empty")
    except Exception as exc:
        reasons.append(f"/public/last-trades:{exc}")

    return [], reasons


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _score_liquidity(snapshot: dict | None) -> float:
    if not isinstance(snapshot, dict):
        return 0.0
    spread_bps = _to_float(snapshot.get("spread_bps"), default=999.0)
    trade_count = _to_float(snapshot.get("trade_count"), default=0.0)
    spread_score = _clip(100.0 - (spread_bps * 0.7), 0.0, 100.0)
    depth_score = _clip(trade_count * 2.0, 0.0, 100.0)
    return round((spread_score * 0.7) + (depth_score * 0.3), 2)


def _score_volatility(snapshot: dict | None) -> float:
    if not isinstance(snapshot, dict):
        return 0.0
    atr_raw = _to_float(snapshot.get("atr_raw"), default=0.0)
    # Favor moderate short-term volatility for mean-reversion style.
    target = 0.015
    distance = abs(atr_raw - target)
    score = 100.0 - _clip((distance / max(target, 1e-6)) * 100.0, 0.0, 100.0)
    return round(score, 2)


def _score_market_quality(snapshot: dict | None) -> float:
    if not isinstance(snapshot, dict):
        return 0.0
    quality_ok = snapshot.get("data_quality_ok") is True
    quality_reason = str(snapshot.get("data_quality_reason", "")).lower()
    score = 100.0 if quality_ok else 40.0
    if "spread_too_wide" in quality_reason:
        score -= 30.0
    if "order_book_tape_mismatch" in quality_reason:
        score -= 20.0
    if "warming_up_history" in quality_reason:
        score -= 20.0
    return round(_clip(score, 0.0, 100.0), 2)


def _score_bounce_setup(snapshot: dict | None) -> float:
    if not isinstance(snapshot, dict):
        return 0.0
    low_24h = _to_float(snapshot.get("low_24h"), default=0.0)
    high_24h = _to_float(snapshot.get("high_24h"), default=0.0)
    price = _to_float(snapshot.get("price"), default=0.0)
    mom = _to_float(snapshot.get("momentum_norm"), default=0.0)
    if high_24h <= low_24h or price <= 0:
        return 0.0
    range_pos = _clip((price - low_24h) / max(high_24h - low_24h, 1e-9), 0.0, 1.0)
    stretch = (1.0 - range_pos) * 100.0
    momentum_adjust = _clip((-mom) * 10.0, -25.0, 25.0)
    return round(_clip(stretch + momentum_adjust, 0.0, 100.0), 2)


def _score_trend_shift(snapshot: dict | None) -> float:
    if not isinstance(snapshot, dict):
        return 0.0
    mom = _to_float(snapshot.get("momentum_norm"), default=0.0)
    score = 50.0 + _clip(mom * 20.0, -50.0, 50.0)
    return round(_clip(score, 0.0, 100.0), 2)


def _regime_suggestion(snapshot: dict, cfg: dict) -> str:
    try:
        regime = detect_regime(snapshot, cfg.get("market_regime", {}))
    except Exception:
        regime = "unknown"
    return str(regime or "unknown").upper()


def _ticker_spread_bps(row: dict) -> float | None:
    bid = _to_float(row.get("bid"), default=0.0)
    ask = _to_float(row.get("ask"), default=0.0)
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = _to_float(row.get("mid"), default=0.0)
    if mid <= 0:
        mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return ((ask - bid) / mid) * 10000.0


def _ticker_fallback_metrics(row: dict) -> dict:
    spread_bps = _ticker_spread_bps(row)
    if spread_bps is None:
        return {
            "liquidity_score": 35.0,
            "volatility_score": 40.0,
            "market_quality_score": 40.0,
            "bounce_setup_score": 45.0,
            "trend_shift_score": 50.0,
            "regime_suggestion": "UNKNOWN",
            "has_market": False,
        }

    spread_score = _clip(100.0 - (spread_bps * 0.7), 0.0, 100.0)
    quality_score = _clip(100.0 - (spread_bps * 0.6), 0.0, 100.0)
    return {
        "liquidity_score": round((spread_score * 0.9) + 10.0, 2),
        "volatility_score": 50.0,
        "market_quality_score": round(quality_score, 2),
        "bounce_setup_score": 50.0,
        "trend_shift_score": 50.0,
        "regime_suggestion": "UNKNOWN",
        "has_market": True,
    }


def build_universe_snapshot(cfg: dict) -> dict:
    started_at = time.time()
    now_ts = time.time()
    tracked_symbols = [
        str(symbol).strip().upper()
        for symbol in (cfg.get("symbols", []) if isinstance(cfg.get("symbols"), list) else [])
        if isinstance(symbol, str) and symbol.strip()
    ]
    tracked_set = set(tracked_symbols)

    allowed_quotes = DEFAULT_ALLOWED_QUOTES
    universe_cfg = cfg.get("universe", {})
    if isinstance(universe_cfg, dict):
        quote_list = universe_cfg.get("allowed_quote_assets")
        if isinstance(quote_list, list):
            parsed = {
                str(item).strip().upper()
                for item in quote_list
                if isinstance(item, str) and item.strip()
            }
            if parsed:
                allowed_quotes = parsed
    snapshot_limit = DEFAULT_ENRICHED_SNAPSHOT_LIMIT
    if isinstance(universe_cfg, dict):
        requested_limit = universe_cfg.get("enriched_snapshot_limit")
        if requested_limit is not None:
            try:
                snapshot_limit = int(requested_limit)
            except (TypeError, ValueError):
                snapshot_limit = DEFAULT_ENRICHED_SNAPSHOT_LIMIT
    snapshot_limit = max(0, min(snapshot_limit, 512))

    rows, source_notes = _fetch_revolut_instruments()
    seen_symbols = set()
    universe_rows = []
    enrichment_attempts = 0
    previous_history = _load_price_history_map()
    next_history: dict[str, list[dict]] = {}

    if not rows:
        for symbol in sorted(tracked_set):
            universe_rows.append(
                {
                    "symbol": symbol,
                    "eligible": False,
                    "reasons": ["universe_source_unavailable"],
                    "quote_asset": symbol.split("-", 1)[1] if "-" in symbol else None,
                    "liquidity_score": 0.0,
                    "volatility_score": 0.0,
                    "market_quality_score": 0.0,
                    "bounce_setup_score": 0.0,
                    "trend_shift_score": 0.0,
                    "regime_suggestion": "UNKNOWN",
                    "overall_universe_score": 0.0,
                    "tracked": True,
                }
            )
    else:
        for raw in rows:
            symbol = _normalize_symbol(
                raw.get("symbol")
                or raw.get("pair")
                or raw.get("instrument")
                or raw.get("name")
                or raw.get("id")
            )
            if not symbol or symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)

            base_asset, quote_asset = _extract_base_quote(raw, symbol)
            reasons = []
            is_active = _is_active_row(raw)
            if not is_active:
                reasons.append("not_tradable")
            if quote_asset and quote_asset not in allowed_quotes:
                reasons.append("unsupported_quote_asset")

            should_enrich = enrichment_attempts < snapshot_limit
            snapshot = None
            if should_enrich:
                enrichment_attempts += 1
                snapshot = fetch_market_snapshot(symbol, cfg)
            current_price = None
            if snapshot is None:
                fallback_metrics = _ticker_fallback_metrics(raw)
                if not fallback_metrics["has_market"]:
                    reasons.append("insufficient_market_data")
                liquidity_score = fallback_metrics["liquidity_score"]
                volatility_score = fallback_metrics["volatility_score"]
                market_quality_score = fallback_metrics["market_quality_score"]
                bounce_setup_score = fallback_metrics["bounce_setup_score"]
                trend_shift_score = fallback_metrics["trend_shift_score"]
                regime_suggestion = fallback_metrics["regime_suggestion"]
                current_price = _extract_ticker_price(raw)
            else:
                quality_ok = snapshot.get("data_quality_ok") is True
                spread_bps = _to_float(snapshot.get("spread_bps"), default=0.0)
                atr_raw = _to_float(snapshot.get("atr_raw"), default=0.0)
                min_atr = _to_float(cfg.get("volatility_filters", {}).get("min_atr"), default=0.0)

                if not quality_ok:
                    reasons.append("market_quality_degraded")
                if spread_bps > 150.0:
                    reasons.append("spread_too_wide")
                if atr_raw < min_atr:
                    reasons.append("volatility_too_low")

                liquidity_score = _score_liquidity(snapshot)
                volatility_score = _score_volatility(snapshot)
                market_quality_score = _score_market_quality(snapshot)
                bounce_setup_score = _score_bounce_setup(snapshot)
                trend_shift_score = _score_trend_shift(snapshot)
                regime_suggestion = _regime_suggestion(snapshot, cfg)
                current_price = _to_float(snapshot.get("price"), default=0.0)
                if current_price <= 0:
                    current_price = _extract_ticker_price(raw)

            entries = _append_price_history_sample(
                symbol=symbol,
                current_price=current_price,
                now_ts=now_ts,
                previous_history=previous_history,
            )
            if entries:
                next_history[symbol] = entries
            change_24h_pct = _compute_change_24h_pct(entries, now_ts, current_price)

            overall = (
                (liquidity_score * 0.25)
                + (volatility_score * 0.2)
                + (market_quality_score * 0.2)
                + (bounce_setup_score * 0.2)
                + (trend_shift_score * 0.15)
            )
            universe_rows.append(
                {
                    "symbol": symbol,
                    "base_asset": base_asset or None,
                    "quote_asset": quote_asset or None,
                    "eligible": len(reasons) == 0,
                    "reasons": reasons,
                    "liquidity_score": round(liquidity_score, 2),
                    "volatility_score": round(volatility_score, 2),
                    "market_quality_score": round(market_quality_score, 2),
                    "bounce_setup_score": round(bounce_setup_score, 2),
                    "trend_shift_score": round(trend_shift_score, 2),
                    "regime_suggestion": regime_suggestion,
                    "overall_universe_score": round(_clip(overall, 0.0, 100.0), 2),
                    "current_price": (
                        None if current_price is None or current_price <= 0 else round(float(current_price), 10)
                    ),
                    "change_24h_pct": (
                        None if change_24h_pct is None else round(float(change_24h_pct), 4)
                    ),
                    "tracked": symbol in tracked_set,
                }
            )

    # Ensure currently tracked symbols are represented even if source payload omitted them.
    for symbol in sorted(tracked_set):
        if any(row.get("symbol") == symbol for row in universe_rows):
            continue
        universe_rows.append(
            {
                "symbol": symbol,
                "eligible": False,
                "reasons": ["tracked_symbol_not_found_in_source"],
                "quote_asset": symbol.split("-", 1)[1] if "-" in symbol else None,
                "liquidity_score": 0.0,
                "volatility_score": 0.0,
                "market_quality_score": 0.0,
                "bounce_setup_score": 0.0,
                "trend_shift_score": 0.0,
                "regime_suggestion": "UNKNOWN",
                "overall_universe_score": 0.0,
                "current_price": None,
                "change_24h_pct": None,
                "tracked": True,
            }
        )

    universe_rows.sort(
        key=lambda row: (
            0 if row.get("eligible") else 1,
            -_to_float(row.get("overall_universe_score"), default=0.0),
            str(row.get("symbol", "")),
        )
    )

    snapshot = {
        "generated_at": time.time(),
        "sync_status": "ok" if rows else "degraded",
        "sync_error": None if rows else "; ".join(source_notes),
        "source_notes": source_notes,
        "rows": universe_rows,
        "summary": {
            "total_symbols": len(universe_rows),
            "eligible_count": sum(1 for row in universe_rows if row.get("eligible")),
            "tracked_count": sum(1 for row in universe_rows if row.get("tracked")),
            "ineligible_count": sum(1 for row in universe_rows if not row.get("eligible")),
            "top_score": max(
                [_to_float(row.get("overall_universe_score"), default=0.0) for row in universe_rows],
                default=0.0,
            ),
            "build_ms": round((time.time() - started_at) * 1000.0, 2),
        },
    }
    write_json_file(UNIVERSE_PRICE_HISTORY_PATH, next_history, use_lock=True)
    write_json_file(UNIVERSE_SNAPSHOT_PATH, snapshot, use_lock=True)
    return snapshot


def read_universe_snapshot(default: dict | None = None) -> dict:
    fallback = default if isinstance(default, dict) else {}
    snapshot = read_json_file(UNIVERSE_SNAPSHOT_PATH, default=fallback, strict=False)
    if isinstance(snapshot, dict):
        return snapshot
    return fallback


def get_universe_snapshot(cfg: dict, *, force_refresh: bool = False) -> dict:
    if force_refresh:
        return build_universe_snapshot(cfg)

    cached = read_universe_snapshot(default={})
    generated_at = _to_float(cached.get("generated_at"), default=0.0)
    if generated_at > 0 and (time.time() - generated_at) <= DEFAULT_UNIVERSE_TTL_SECONDS:
        return cached
    return build_universe_snapshot(cfg)
