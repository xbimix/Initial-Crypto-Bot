from __future__ import annotations

from typing import Any

from strategy.data_quality_gate import evaluate_entry_data_quality


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
    return _as_dict(route_gates.get("breakout_momentum"))


def _extract_prices(snapshot: dict[str, Any]) -> list[float]:
    ohlcv_rows = snapshot.get("ohlcv")
    if isinstance(ohlcv_rows, list):
        prices_from_ohlcv: list[float] = []
        for row in ohlcv_rows:
            if not isinstance(row, dict):
                continue
            value = _as_float(row.get("close"), default=None)
            if value is None or value <= 0:
                continue
            prices_from_ohlcv.append(float(value))
        if len(prices_from_ohlcv) >= 12:
            return prices_from_ohlcv

    rows = snapshot.get("recent_prices")
    if not isinstance(rows, list):
        return []
    prices: list[float] = []
    for raw in rows:
        value = _as_float(raw, default=None)
        if value is None or value <= 0:
            continue
        prices.append(float(value))
    return prices


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
    _ = (high_24h, low_24h, vwap, prev_momentum, range_pos)
    data_quality_allowed, blocked_reason = evaluate_entry_data_quality(
        snapshot=snapshot,
        cfg=cfg,
    )
    if not data_quality_allowed:
        return "HOLD", str(blocked_reason or "data_quality_failed")

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
    if atr_value is None or atr_value <= 0:
        return "HOLD", "breakout_momentum_missing_volatility"
    atr_multiplier = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="atr_multiplier",
                fallback=0.75,
            ),
            0.75,
        )
        or 0.75,
        0.0,
    )
    if atr_value < (max(min_atr, 0.0) * atr_multiplier):
        return "HOLD", "breakout_momentum_volatility_too_low"

    prices = _extract_prices(snapshot)
    if len(prices) < 12:
        return "HOLD", "breakout_momentum_insufficient_history"

    prior_window = prices[-12:-6]
    trigger_window = prices[-6:]
    prior_high = max(prior_window)
    prior_low = min(prior_window)
    prior_range_pct = ((prior_high - prior_low) / max(prior_low, 1e-9)) * 100.0

    compression_window = trigger_window[:-1]
    compression_high = max(compression_window)
    compression_low = min(compression_window)
    compression_range_pct = ((compression_high - compression_low) / max(compression_low, 1e-9)) * 100.0
    compression_ratio = (
        (compression_range_pct / prior_range_pct)
        if prior_range_pct > 0
        else 1.0
    )
    compression_ratio_max = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="compression_ratio_max",
                fallback=0.9,
            ),
            0.9,
        )
        or 0.9,
        0.0,
    )
    if compression_ratio > compression_ratio_max:
        return "HOLD", "breakout_momentum_no_compression"

    breakout_buffer = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="breakout_buffer",
                fallback=0.0012,
            ),
            0.0012,
        )
        or 0.0012,
        0.0,
    )
    if price <= (prior_high * (1.0 + breakout_buffer)):
        return "HOLD", "breakout_momentum_not_triggered"

    breakout_price = trigger_window[-1]
    follow_through_buffer = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="follow_through_buffer",
                fallback=0.0004,
            ),
            0.0004,
        )
        or 0.0004,
        0.0,
    )
    if breakout_price <= (compression_high * (1.0 + follow_through_buffer)):
        return "HOLD", "breakout_momentum_no_follow_through"
    if len(trigger_window) >= 2 and trigger_window[-1] <= trigger_window[-2]:
        return "HOLD", "breakout_momentum_breakout_not_sustained"

    min_momentum = _as_float(
        _gate_value(
            mode_cfg=mode_cfg,
            gate_defaults=gate_defaults,
            key="min_momentum",
            fallback=0.25,
        ),
        0.25,
    )
    if min_momentum is not None and float(momentum) < min_momentum:
        return "HOLD", "breakout_momentum_momentum_not_ready"

    overextended_z_score = _as_float(
        _gate_value(
            mode_cfg=mode_cfg,
            gate_defaults=gate_defaults,
            key="overextended_z_score",
            fallback=2.2,
        ),
        2.2,
    )
    if overextended_z_score is not None and z_score is not None and z_score > overextended_z_score:
        return "HOLD", "breakout_momentum_overextended"

    score_mult = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="score_multiplier",
                fallback=0.9,
            ),
            0.9,
        )
        or 0.9,
        0.0,
    )
    score_floor = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="score_floor",
                fallback=55.0,
            ),
            55.0,
        )
        or 55.0,
        0.0,
    )
    threshold = max(float(min_score_to_buy) * score_mult, score_floor)
    if float(score) < threshold:
        return "HOLD", "breakout_momentum_score_below_threshold"

    return "BUY", "breakout_momentum_entry_v1"
