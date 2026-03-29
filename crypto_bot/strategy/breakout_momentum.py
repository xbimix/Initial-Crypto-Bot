from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed:  # NaN guard
        return default
    return parsed


def _gate_value(
    *,
    mode_cfg: dict[str, Any],
    gate_defaults: dict[str, Any],
    key: str,
    fallback: Any,
) -> Any:
    if key in mode_cfg:
        return mode_cfg.get(key)
    if key in gate_defaults:
        return gate_defaults.get(key)
    return fallback


def _breakout_gate_defaults(cfg: dict[str, Any]) -> dict[str, Any]:
    strategy_defaults = _as_dict(cfg.get("strategy_defaults"))
    route_gates = _as_dict(strategy_defaults.get("route_gates"))
    route_defaults = _as_dict(route_gates.get("breakout_momentum"))
    # Backward-compatible legacy top-level route_gates support.
    legacy_route_gates = _as_dict(cfg.get("route_gates"))
    legacy_route_defaults = _as_dict(legacy_route_gates.get("breakout_momentum"))
    merged = dict(route_defaults)
    if legacy_route_defaults:
        merged.update(legacy_route_defaults)
    return merged


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
    data_quality_ok = snapshot.get("data_quality_ok")
    if data_quality_ok is not True:
        reason = snapshot.get("data_quality_reason")
        if not isinstance(reason, str) or not reason.strip():
            reason = "data_quality_missing" if data_quality_ok is None else "data_quality_failed"
        return "HOLD", str(reason)

    if regime in blocked_regimes:
        return "HOLD", f"regime_{regime}"

    mode_cfg = cfg.get("breakout_momentum", {})
    if not isinstance(mode_cfg, dict):
        mode_cfg = {}
    gate_defaults = _breakout_gate_defaults(cfg)

    required_trades = max(
        min_trades,
        int(
            _as_float(
                _gate_value(
                    mode_cfg=mode_cfg,
                    gate_defaults=gate_defaults,
                    key="min_trades",
                    fallback=min_trades,
                ),
                min_trades,
            )
            or min_trades
        ),
    )
    if int(trades) < required_trades:
        return "HOLD", "breakout_momentum_insufficient_trades"

    atr_value = _as_float(atr, default=None)
    min_mode_atr = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="min_atr",
                fallback=min_atr,
            ),
            min_atr,
        )
        or min_atr,
        min_atr,
        0.0,
    )
    if atr_value is None or atr_value <= 0:
        return "HOLD", "breakout_momentum_missing_volatility"
    if atr_value < min_mode_atr:
        return "HOLD", "breakout_momentum_volatility_too_low"

    atr_pct = _as_float(snapshot.get("atr_pct"), default=None)
    if atr_pct is None:
        atr_pct = atr_value
    min_breakout_atr_pct = _as_float(
        _gate_value(
            mode_cfg=mode_cfg,
            gate_defaults=gate_defaults,
            key="min_breakout_atr_pct",
            fallback=0.00010,
        ),
        0.00010,
    )
    if min_breakout_atr_pct is not None and atr_pct is not None and atr_pct < min_breakout_atr_pct:
        return "HOLD", "breakout_momentum_atr_compressed"

    adx = _as_float(snapshot.get("adx"), default=None)
    min_adx = _as_float(
        _gate_value(
            mode_cfg=mode_cfg,
            gate_defaults=gate_defaults,
            key="min_adx",
            fallback=18.0,
        ),
        18.0,
    )
    if adx is not None and min_adx is not None and adx < min_adx:
        return "HOLD", "breakout_momentum_adx_too_low"

    volume_ratio = _as_float(snapshot.get("volume_ratio"), default=None)
    min_volume_ratio = _as_float(
        _gate_value(
            mode_cfg=mode_cfg,
            gate_defaults=gate_defaults,
            key="min_volume_ratio",
            fallback=1.05,
        ),
        1.05,
    )
    if volume_ratio is not None and min_volume_ratio is not None and volume_ratio < min_volume_ratio:
        return "HOLD", "breakout_momentum_volume_not_confirmed"

    structure_prices_raw = snapshot.get("recent_prices", [])
    structure_prices: list[float] = []
    if isinstance(structure_prices_raw, list):
        for value in structure_prices_raw:
            numeric = _as_float(value, default=None)
            if numeric is not None and numeric > 0:
                structure_prices.append(float(numeric))
    structure_lookback = int(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="compression_lookback_points",
                fallback=8,
            ),
            8,
        )
        or 8
    )
    structure_lookback = max(structure_lookback, 8)
    if len(structure_prices) < structure_lookback:
        return "HOLD", "breakout_momentum_insufficient_compression_history"

    structure_window = structure_prices[-structure_lookback:]
    half = structure_lookback // 2
    prior_window = structure_window[:half]
    recent_window = structure_window[half:]
    if len(prior_window) < 2 or len(recent_window) < 2:
        return "HOLD", "breakout_momentum_insufficient_compression_history"

    prior_range = max(prior_window) - min(prior_window)
    recent_range = max(recent_window) - min(recent_window)
    max_compression_ratio = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="max_compression_ratio",
                fallback=0.92,
            ),
            0.92,
        )
        or 0.92,
        0.1,
    )
    if prior_range > 0 and (recent_range / prior_range) > max_compression_ratio:
        return "HOLD", "breakout_momentum_no_compression"

    breakout_confirm_pct = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="breakout_confirm_pct",
                fallback=0.0015,
            ),
            0.0015,
        )
        or 0.0015,
        0.0,
    )
    prior_high_before_breakout = max(structure_window[:-1]) if len(structure_window) > 1 else max(structure_window)
    if price < prior_high_before_breakout * (1.0 + breakout_confirm_pct):
        return "HOLD", "breakout_momentum_breakout_unconfirmed"

    max_late_entry_pct = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="max_late_entry_pct",
                fallback=0.045,
            ),
            0.045,
        )
        or 0.045,
        0.0,
    )
    if price > prior_high_before_breakout * (1.0 + max_late_entry_pct):
        return "HOLD", "breakout_momentum_too_late"

    require_retest = bool(
        _gate_value(
            mode_cfg=mode_cfg,
            gate_defaults=gate_defaults,
            key="require_retest_confirmation",
            fallback=False,
        )
    )
    if require_retest and len(structure_window) >= 4:
        retest_tolerance_pct = max(
            _as_float(
                _gate_value(
                    mode_cfg=mode_cfg,
                    gate_defaults=gate_defaults,
                    key="retest_tolerance_pct",
                    fallback=0.003,
                ),
                0.003,
            )
            or 0.003,
            0.0,
        )
        recent_low = min(structure_window[-4:])
        if recent_low > prior_high_before_breakout * (1.0 + retest_tolerance_pct):
            return "HOLD", "breakout_momentum_wait_retest"

    if high_24h <= low_24h:
        return "HOLD", "breakout_momentum_insufficient_range_data"

    breakout_buffer_pct = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="breakout_buffer_pct",
                fallback=0.0025,
            ),
            0.0025,
        )
        or 0.0025,
        0.0,
    )
    breakout_trigger = high_24h * (1.0 - breakout_buffer_pct)
    if price < breakout_trigger:
        return "HOLD", "breakout_momentum_waiting_breakout"

    min_range_pos = _as_float(
        _gate_value(
            mode_cfg=mode_cfg,
            gate_defaults=gate_defaults,
            key="min_range_pos",
            fallback=0.72,
        ),
        0.72,
    )
    if min_range_pos is not None and range_pos is not None and range_pos < min_range_pos:
        return "HOLD", "breakout_momentum_not_at_range_high"

    min_entry_z = _as_float(
        _gate_value(
            mode_cfg=mode_cfg,
            gate_defaults=gate_defaults,
            key="min_entry_z_score",
            fallback=-0.05,
        ),
        -0.05,
    )
    if min_entry_z is not None and z_score is not None and z_score < min_entry_z:
        return "HOLD", "breakout_momentum_not_confirmed_above_vwap"

    max_entry_z = _as_float(
        _gate_value(
            mode_cfg=mode_cfg,
            gate_defaults=gate_defaults,
            key="max_entry_z_score",
            fallback=2.2,
        ),
        2.2,
    )
    if max_entry_z is not None and z_score is not None and z_score > max_entry_z:
        return "HOLD", "breakout_momentum_overextended"

    min_entry_score = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="min_score_to_buy",
                fallback=min_score_to_buy,
            ),
            min_score_to_buy,
        )
        or min_score_to_buy,
        0.0,
    )
    if float(score) < min_entry_score:
        return "HOLD", "breakout_momentum_score_below_threshold"

    min_momentum = _as_float(
        _gate_value(
            mode_cfg=mode_cfg,
            gate_defaults=gate_defaults,
            key="min_momentum",
            fallback=0.45,
        ),
        0.45,
    )
    if min_momentum is not None and float(momentum) < min_momentum:
        return "HOLD", "breakout_momentum_not_ready"

    if prev_momentum is not None and float(momentum) < float(prev_momentum):
        return "HOLD", "breakout_momentum_weakening"

    if vwap is None:
        return "HOLD", "breakout_momentum_missing_vwap"

    return "BUY", "breakout_momentum_entry"
