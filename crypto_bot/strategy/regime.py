from __future__ import annotations

from typing import Any


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed:  # NaN guard
        return default
    return parsed


def _cfg_float(cfg: dict[str, Any], key: str, fallback: float) -> float:
    value = _to_float(cfg.get(key), fallback)
    if value is None:
        return fallback
    return float(value)


def _recent_prices(snapshot: dict[str, Any], lookback: int) -> list[float]:
    rows = snapshot.get("recent_prices", [])
    if not isinstance(rows, list):
        return []
    clean: list[float] = []
    for raw in rows[-max(lookback, 2):]:
        value = _to_float(raw)
        if value is None or value <= 0:
            continue
        clean.append(float(value))
    return clean


def _flip_rate(prices: list[float]) -> float | None:
    if len(prices) < 6:
        return None
    signs: list[int] = []
    for idx in range(1, len(prices)):
        delta = prices[idx] - prices[idx - 1]
        if delta > 0:
            signs.append(1)
        elif delta < 0:
            signs.append(-1)
    if len(signs) < 3:
        return None
    flips = 0
    for idx in range(1, len(signs)):
        if signs[idx] != signs[idx - 1]:
            flips += 1
    return flips / max(1, len(signs) - 1)


def detect_regime(snapshot: dict[str, Any], regime_cfg: dict | None = None) -> str:
    regime_cfg = regime_cfg or {}

    price = _to_float(snapshot.get("price"))
    high_24h = _to_float(snapshot.get("high_24h"))
    low_24h = _to_float(snapshot.get("low_24h"))
    if price is None or price <= 0:
        return "unknown"

    ema_50 = _to_float(snapshot.get("ema_50"))
    ema_200 = _to_float(snapshot.get("ema_200"))
    ema_50_slope = _to_float(snapshot.get("ema_50_slope"), 0.0) or 0.0
    adx = _to_float(snapshot.get("adx"))
    rsi = _to_float(snapshot.get("rsi"))
    momentum = _to_float(snapshot.get("momentum_norm"))
    if momentum is None:
        momentum = _to_float(snapshot.get("momentum"), 0.0) or 0.0
    atr_pct = _to_float(snapshot.get("atr_pct"))
    if atr_pct is None:
        atr_pct = _to_float(snapshot.get("atr"), 0.0) or 0.0
    volume_ratio = _to_float(snapshot.get("volume_ratio"))

    # Keep a meaningful breakout buffer to avoid classifying minor drift as breakout.
    breakout_buffer_pct = max(_cfg_float(regime_cfg, "breakout_buffer_pct", 0.0040), 0.0)
    breakout_momentum_min = _cfg_float(regime_cfg, "breakout_momentum_min", 0.25)
    breakout_volume_ratio_min = _cfg_float(regime_cfg, "breakout_volume_ratio_min", 1.05)
    trend_adx_min = _cfg_float(regime_cfg, "trend_adx_min", 20.0)
    trend_slope_min = _cfg_float(regime_cfg, "trend_slope_min", 0.0)
    momentum_up_min = _cfg_float(regime_cfg, "momentum_up_min", 0.20)
    momentum_choppy_abs_max = abs(_cfg_float(regime_cfg, "momentum_choppy_abs_max", 0.18))
    choppy_adx_max = _cfg_float(regime_cfg, "choppy_adx_max", 17.0)
    choppy_flip_rate_min = _cfg_float(regime_cfg, "choppy_flip_rate_min", 0.52)
    ema_compression_max_pct = _cfg_float(regime_cfg, "ema_compression_max_pct", 0.0045)
    low_vol_atr_pct_max = _cfg_float(regime_cfg, "low_vol_atr_pct_max", 0.00018)
    volatile_atr_pct_min = _cfg_float(regime_cfg, "volatile_atr_pct_min", 0.00055)

    recent = _recent_prices(snapshot, lookback=48)
    structure_high = max(recent) if recent else high_24h
    structure_low = min(recent) if recent else low_24h
    if structure_high is None:
        structure_high = high_24h
    if structure_low is None:
        structure_low = low_24h

    if structure_high is None or structure_low is None:
        return "unknown"
    if structure_high <= 0 or structure_low <= 0 or structure_high <= structure_low:
        return "unknown"

    range_width = structure_high - structure_low
    range_pos = (price - structure_low) / range_width if range_width > 0 else None
    range_pct = range_width / price if price > 0 else 0.0

    ema_gap_pct = None
    if ema_50 is not None and ema_200 is not None and price > 0:
        ema_gap_pct = abs(ema_50 - ema_200) / price

    flip_rate = _flip_rate(recent)
    low_adx = adx is not None and adx < choppy_adx_max
    weak_momentum = abs(float(momentum)) <= momentum_choppy_abs_max
    ema_compressed = ema_gap_pct is not None and ema_gap_pct <= ema_compression_max_pct
    frequent_flips = flip_rate is not None and flip_rate >= choppy_flip_rate_min

    trend_adx_ok = adx is None or adx >= trend_adx_min
    trend_up = (
        ema_50 is not None
        and ema_200 is not None
        and price >= ema_50
        and ema_50 > ema_200
        and ema_50_slope > trend_slope_min
        and trend_adx_ok
    )
    trend_down = (
        ema_50 is not None
        and ema_200 is not None
        and price <= ema_50
        and ema_50 < ema_200
        and ema_50_slope < -trend_slope_min
        and trend_adx_ok
    )
    if trend_up:
        return "trend_up"
    if trend_down:
        return "trend_down"

    breakout_volume_ok = True
    if volume_ratio is not None:
        breakout_volume_ok = volume_ratio >= breakout_volume_ratio_min

    breakout_atr_ok = atr_pct >= (low_vol_atr_pct_max * 0.95)
    breakout_up = (
        price >= (structure_high * (1.0 + breakout_buffer_pct))
        and momentum >= breakout_momentum_min
        and breakout_volume_ok
        and breakout_atr_ok
    )
    breakout_down = (
        price <= (structure_low * (1.0 - breakout_buffer_pct))
        and momentum <= -breakout_momentum_min
        and breakout_volume_ok
        and breakout_atr_ok
    )
    if breakout_up:
        return "breakout_up"
    if breakout_down:
        return "breakout_down"

    momentum_signal = False
    if rsi is not None and rsi >= 60.0:
        momentum_signal = True
    if momentum >= momentum_up_min:
        momentum_signal = True
    if momentum_signal and not trend_down:
        return "momentum_up"

    if atr_pct <= low_vol_atr_pct_max and not breakout_up and not breakout_down:
        return "low_vol"

    if atr_pct >= volatile_atr_pct_min and not trend_up and not trend_down:
        return "volatile"

    if (
        low_adx
        and weak_momentum
        and (ema_compressed or frequent_flips)
    ):
        return "choppy"

    if range_pos is not None and 0.12 <= range_pos <= 0.88 and range_pct > 0:
        return "range"

    return "unknown"
