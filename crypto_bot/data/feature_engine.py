from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

try:
    from analysis.indicators import calculate_rsi as _default_calculate_rsi
except ModuleNotFoundError:
    from crypto_bot.analysis.indicators import calculate_rsi as _default_calculate_rsi

from data.state_store import MarketDataStateStore


@dataclass(frozen=True)
class FeatureResult:
    features: dict[str, Any]
    cache_hit: bool
    version_key: str


def _weighted_average(prices: list[float], sizes: list[float]) -> float:
    total_size = sum(sizes)
    if total_size <= 0:
        return statistics.mean(prices)
    return sum(p * s for p, s in zip(prices, sizes)) / total_size


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema_val = values[0]
    for price in values[1:]:
        ema_val = price * k + ema_val * (1 - k)
    return ema_val


def _build_indicator_features(
    prices: list[float],
    weights: list[float],
    *,
    atr_floor: float,
    rsi_fn,
) -> dict[str, Any]:
    deltas = [
        abs(prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(1, len(prices))
        if prices[i - 1] > 0
    ]
    atr_raw = statistics.median(deltas) if deltas else 0.0
    atr = max(float(atr_raw), float(atr_floor))
    vwap = _weighted_average(prices, weights)
    median_price = statistics.median(prices)
    rsi = rsi_fn(prices, period=14)
    ema_50 = _ema(prices[-100:], 50)
    ema_200 = _ema(prices[-250:], 200)
    ema_50_prev = _ema(prices[-101:-1], 50) if len(prices) > 101 else None
    ema_50_slope = (ema_50 - ema_50_prev) if ema_50 is not None and ema_50_prev is not None else None
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


def _fingerprint(
    *,
    history_source: str,
    history_version: int,
    latest_open_time: int | None,
    prices: list[float],
) -> str:
    if history_source == "sqlite_candles" and latest_open_time is not None:
        return f"sqlite:{int(latest_open_time)}"
    latest_px = prices[-1] if prices else 0.0
    return f"{history_source}:{int(history_version)}:{len(prices)}:{latest_px:.10f}"


def resolve_indicator_features(
    *,
    store: MarketDataStateStore,
    symbol: str,
    timeframe: str,
    history_source: str,
    history_version: int,
    latest_open_time: int | None,
    prices: list[float],
    weights: list[float],
    atr_floor: float,
    rsi_fn=None,
) -> FeatureResult:
    cache_key = (
        f"{str(symbol).strip().upper()}:"
        f"{str(timeframe).strip().lower()}:"
        f"{str(history_source).strip().lower()}"
    )
    fp = _fingerprint(
        history_source=history_source,
        history_version=history_version,
        latest_open_time=latest_open_time,
        prices=prices,
    )
    cached = store.get_indicator_features(cache_key=cache_key, fingerprint=fp)
    if isinstance(cached, dict):
        return FeatureResult(features=dict(cached), cache_hit=True, version_key=fp)

    features = _build_indicator_features(
        prices,
        weights,
        atr_floor=atr_floor,
        rsi_fn=rsi_fn or _default_calculate_rsi,
    )
    store.set_indicator_features(
        cache_key=cache_key,
        fingerprint=fp,
        features=features,
    )
    return FeatureResult(features=features, cache_hit=False, version_key=fp)
