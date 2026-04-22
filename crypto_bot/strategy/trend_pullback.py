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


def _trend_gate_defaults(cfg: dict[str, Any]) -> dict[str, Any]:
    strategy_defaults = _as_dict(cfg.get("strategy_defaults"))
    route_gates = _as_dict(strategy_defaults.get("route_gates"))
    return _as_dict(route_gates.get("trend_pullback"))


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
    _ = (high_24h, low_24h, vwap, range_pos)
    data_quality_allowed, blocked_reason = evaluate_entry_data_quality(
        snapshot=snapshot,
        cfg=cfg,
    )
    if not data_quality_allowed:
        return "HOLD", str(blocked_reason or "data_quality_failed")

    if regime in blocked_regimes:
        return "HOLD", f"regime_{regime}"

    mode_cfg = cfg.get("trend_pullback", {})
    if not isinstance(mode_cfg, dict):
        mode_cfg = {}
    gate_defaults = _trend_gate_defaults(cfg)

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
        return "HOLD", "trend_pullback_insufficient_trades"

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
        0.0,
    )
    if atr_value is None or atr_value <= 0:
        return "HOLD", "trend_pullback_missing_volatility"
    if atr_value < min_mode_atr:
        return "HOLD", "trend_pullback_volatility_too_low"

    prices = _extract_prices(snapshot)
    if len(prices) < 12:
        return "HOLD", "trend_pullback_insufficient_history"

    short_window = prices[-3:]
    medium_window = prices[-8:]
    short_ma = sum(short_window) / len(short_window)
    medium_ma = sum(medium_window) / len(medium_window)
    if short_ma < medium_ma:
        return "HOLD", "trend_pullback_no_uptrend"

    prior_swing_window = prices[-12:-8]
    trend_swing_window = prices[-8:-4]
    prior_swing_high = max(prior_swing_window)
    prior_swing_low = min(prior_swing_window)
    trend_swing_high = max(trend_swing_window)
    trend_swing_low = min(trend_swing_window)
    higher_high_buffer = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="higher_high_buffer",
                fallback=0.0005,
            ),
            0.0005,
        )
        or 0.0005,
        0.0,
    )
    higher_low_buffer = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="higher_low_buffer",
                fallback=0.0002,
            ),
            0.0002,
        )
        or 0.0002,
        0.0,
    )
    if trend_swing_high <= (prior_swing_high * (1.0 + higher_high_buffer)):
        return "HOLD", "trend_pullback_missing_higher_high"
    if trend_swing_low <= (prior_swing_low * (1.0 + higher_low_buffer)):
        return "HOLD", "trend_pullback_missing_higher_low"

    prior_swing = max(prices[-8:-4])
    pullback_low = min(prices[-4:])
    min_pullback_pct = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="min_pullback_pct",
                fallback=0.0025,
            ),
            0.0025,
        )
        or 0.0025,
        0.0,
    )
    structure_break_pct = max(
        _as_float(
            _gate_value(
                mode_cfg=mode_cfg,
                gate_defaults=gate_defaults,
                key="structure_break_pct",
                fallback=0.005,
            ),
            0.005,
        )
        or 0.005,
        0.0,
    )
    if pullback_low >= (prior_swing * (1.0 - min_pullback_pct)):
        return "HOLD", "trend_pullback_no_pullback"
    if pullback_low <= (prior_swing_low * (1.0 - structure_break_pct)):
        return "HOLD", "trend_pullback_pullback_broke_structure"

    if price < short_ma:
        return "HOLD", "trend_pullback_recovery_not_confirmed"

    min_momentum = _as_float(
        _gate_value(
            mode_cfg=mode_cfg,
            gate_defaults=gate_defaults,
            key="min_momentum",
            fallback=0.08,
        ),
        0.08,
    )
    if min_momentum is not None and float(momentum) < min_momentum:
        return "HOLD", "trend_pullback_momentum_not_ready"

    prev_mom_value = _as_float(prev_momentum, default=None)
    if prev_mom_value is not None and float(momentum) < prev_mom_value:
        return "HOLD", "trend_pullback_momentum_weakening"

    overextended_z_score = _as_float(
        _gate_value(
            mode_cfg=mode_cfg,
            gate_defaults=gate_defaults,
            key="overextended_z_score",
            fallback=1.2,
        ),
        1.2,
    )
    if overextended_z_score is not None and z_score is not None and z_score > overextended_z_score:
        return "HOLD", "trend_pullback_overextended"

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
                fallback=50.0,
            ),
            50.0,
        )
        or 50.0,
        0.0,
    )
    threshold = max(float(min_score_to_buy) * score_mult, score_floor)
    if float(score) < threshold:
        return "HOLD", "trend_pullback_score_below_threshold"

    return "BUY", "trend_pullback_entry_v1"
