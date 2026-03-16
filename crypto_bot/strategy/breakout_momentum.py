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


def evaluate_breakout_momentum_entry(
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

    mode_cfg = cfg.get("breakout_momentum", {})
    if not isinstance(mode_cfg, dict):
        mode_cfg = {}

    required_trades = max(min_trades, int(_as_float(mode_cfg.get("min_trades"), min_trades) or min_trades))
    if int(trades) < required_trades:
        return "HOLD", "breakout_momentum_insufficient_trades"

    atr_value = _as_float(atr, default=None)
    min_mode_atr = max(_as_float(mode_cfg.get("min_atr"), min_atr) or min_atr, min_atr, 0.0)
    if atr_value is None or atr_value <= 0:
        return "HOLD", "breakout_momentum_missing_volatility"
    if atr_value < min_mode_atr:
        return "HOLD", "breakout_momentum_volatility_too_low"

    if high_24h <= low_24h:
        return "HOLD", "breakout_momentum_insufficient_range_data"

    breakout_buffer_pct = max(_as_float(mode_cfg.get("breakout_buffer_pct"), 0.0025) or 0.0025, 0.0)
    breakout_trigger = high_24h * (1.0 - breakout_buffer_pct)
    if price < breakout_trigger:
        return "HOLD", "breakout_momentum_waiting_breakout"

    min_range_pos = _as_float(mode_cfg.get("min_range_pos"), 0.72)
    if min_range_pos is not None and range_pos is not None and range_pos < min_range_pos:
        return "HOLD", "breakout_momentum_not_at_range_high"

    min_entry_z = _as_float(mode_cfg.get("min_entry_z_score"), -0.05)
    if min_entry_z is not None and z_score is not None and z_score < min_entry_z:
        return "HOLD", "breakout_momentum_not_confirmed_above_vwap"

    max_entry_z = _as_float(mode_cfg.get("max_entry_z_score"), 2.2)
    if max_entry_z is not None and z_score is not None and z_score > max_entry_z:
        return "HOLD", "breakout_momentum_overextended"

    min_entry_score = max(_as_float(mode_cfg.get("min_score_to_buy"), min_score_to_buy) or min_score_to_buy, 0.0)
    if float(score) < min_entry_score:
        return "HOLD", "breakout_momentum_score_below_threshold"

    min_momentum = _as_float(mode_cfg.get("min_momentum"), 0.45)
    if min_momentum is not None and float(momentum) < min_momentum:
        return "HOLD", "breakout_momentum_not_ready"

    if prev_momentum is not None and float(momentum) < float(prev_momentum):
        return "HOLD", "breakout_momentum_weakening"

    if vwap is None:
        return "HOLD", "breakout_momentum_missing_vwap"

    return "BUY", "breakout_momentum_entry"

