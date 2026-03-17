from __future__ import annotations

from typing import Any


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed:  # NaN guard
        return default
    return parsed


def evaluate_trend_pullback_entry(
    *,
    snapshot: dict[str, Any],
    price: float,
    momentum: float,
    trades: int,
    high_24h: float,
    low_24h: float,
    atr: float | None,
    vwap: float | None,
    z_score: float | None,
    prev_momentum: float | None,
    min_trades: int,
    min_atr: float,
    min_score_to_buy: float,
    blocked_regimes: set[str],
    regime: str,
    score: float,
    range_pos: float | None,
    cfg: dict[str, Any],
) -> tuple[str, str]:
    if not snapshot.get("data_quality_ok", True):
        return "HOLD", str(snapshot.get("data_quality_reason", "data_quality_failed"))

    if regime in blocked_regimes:
        return "HOLD", f"regime_{regime}"

    mode_cfg = cfg.get("trend_pullback", {})
    if not isinstance(mode_cfg, dict):
        mode_cfg = {}

    required_trades = max(min_trades, int(_as_float(mode_cfg.get("min_trades"), min_trades) or min_trades))
    if int(trades) < required_trades:
        return "HOLD", "trend_pullback_insufficient_trades"

    atr_value = _as_float(atr, default=None)
    min_mode_atr = max(_as_float(mode_cfg.get("min_atr"), min_atr) or min_atr, min_atr, 0.0)
    if atr_value is None or atr_value <= 0:
        return "HOLD", "trend_pullback_missing_volatility"
    if atr_value < min_mode_atr:
        return "HOLD", "trend_pullback_volatility_too_low"

    ema_50 = _as_float(snapshot.get("ema_50"), default=None)
    ema_200 = _as_float(snapshot.get("ema_200"), default=None)
    if ema_50 is None or ema_200 is None:
        return "HOLD", "trend_pullback_missing_trend_baseline"
    if ema_50 <= ema_200:
        return "HOLD", "trend_pullback_not_uptrend"
    ema_50_slope = _as_float(snapshot.get("ema_50_slope"), default=None)
    if ema_50_slope is not None and ema_50_slope <= 0:
        return "HOLD", "trend_pullback_flat_or_negative_slope"

    structure_prices_raw = snapshot.get("recent_prices", [])
    structure_prices: list[float] = []
    if isinstance(structure_prices_raw, list):
        for value in structure_prices_raw:
            numeric = _as_float(value, default=None)
            if numeric is not None and numeric > 0:
                structure_prices.append(float(numeric))
    structure_lookback = int(_as_float(mode_cfg.get("structure_lookback_points"), 8) or 8)
    structure_lookback = max(structure_lookback, 6)
    if len(structure_prices) < structure_lookback:
        return "HOLD", "trend_pullback_insufficient_structure_history"

    structure_window = structure_prices[-structure_lookback:]
    half = structure_lookback // 2
    older_window = structure_window[:half]
    newer_window = structure_window[half:]
    if len(older_window) < 2 or len(newer_window) < 2:
        return "HOLD", "trend_pullback_insufficient_structure_history"

    min_higher_high_pct = max(_as_float(mode_cfg.get("min_higher_high_pct"), 0.001) or 0.001, 0.0)
    min_higher_low_pct = max(_as_float(mode_cfg.get("min_higher_low_pct"), 0.0) or 0.0, 0.0)
    older_high = max(older_window)
    newer_high = max(newer_window)
    older_low = min(older_window)
    newer_low = min(newer_window)
    if newer_high <= older_high * (1.0 + min_higher_high_pct):
        return "HOLD", "trend_pullback_no_higher_high"
    if newer_low <= older_low * (1.0 + min_higher_low_pct):
        return "HOLD", "trend_pullback_no_higher_low"

    bounce_confirm_pct = max(_as_float(mode_cfg.get("bounce_confirm_pct"), 0.001) or 0.001, 0.0)
    if price < newer_low * (1.0 + bounce_confirm_pct):
        return "HOLD", "trend_pullback_wait_bounce_confirmation"

    pullback_buffer_pct = max(_as_float(mode_cfg.get("pullback_buffer_pct"), 0.005) or 0.005, 0.0)
    pullback_depth_pct = max(_as_float(mode_cfg.get("pullback_depth_pct"), 0.03) or 0.03, 0.0)
    pullback_ceiling = ema_50 * (1.0 + pullback_buffer_pct)
    pullback_floor = ema_50 * (1.0 - pullback_depth_pct)

    if price > pullback_ceiling:
        return "HOLD", "trend_pullback_wait_pullback"
    if price < pullback_floor:
        return "HOLD", "trend_pullback_too_deep"

    max_range_pos = _as_float(mode_cfg.get("max_range_pos"), 0.82)
    if max_range_pos is not None and range_pos is not None and range_pos > max_range_pos:
        return "HOLD", "trend_pullback_too_extended"

    max_entry_z = _as_float(mode_cfg.get("max_entry_z_score"), 0.85)
    if max_entry_z is not None and z_score is not None and z_score > max_entry_z:
        return "HOLD", "trend_pullback_overextended"

    min_entry_score = max(_as_float(mode_cfg.get("min_score_to_buy"), min_score_to_buy) or min_score_to_buy, 0.0)
    if float(score) < min_entry_score:
        return "HOLD", "trend_pullback_score_below_threshold"

    min_momentum = _as_float(mode_cfg.get("min_momentum"), 0.05)
    if min_momentum is not None and float(momentum) < min_momentum:
        return "HOLD", "trend_pullback_momentum_not_ready"

    if prev_momentum is not None and float(momentum) < float(prev_momentum):
        return "HOLD", "trend_pullback_momentum_weakening"

    if high_24h <= low_24h:
        return "HOLD", "trend_pullback_insufficient_range_data"
    if vwap is None:
        return "HOLD", "trend_pullback_missing_vwap"

    return "BUY", "trend_pullback_entry"
