from __future__ import annotations

from typing import Any


WINDOWS_MINUTES = [
    ("1h", 60),
    ("4h", 240),
    ("8h", 480),
    ("12h", 720),
    ("16h", 960),
    ("24h", 1440),
    ("3d", 4320),
    ("7d", 10080),
]


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed:  # NaN guard
        return default
    return parsed


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _label(score: float) -> str:
    if score >= 72.0:
        return "HIGH"
    if score >= 48.0:
        return "MEDIUM"
    return "LOW"


def _quality_status(
    *,
    stale: bool,
    supported_key_windows: bool,
    supported_count: int,
) -> str:
    if stale:
        return "STALE"
    if not supported_key_windows:
        return "UNSUPPORTED_WINDOW"
    if supported_count < 3:
        return "INSUFFICIENT"
    if supported_count < 5:
        return "PARTIAL"
    return "GOOD"


def evaluate_regime_v2(
    *,
    snapshot: dict[str, Any],
    now_epoch: float,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg or {}
    strategy_defaults = cfg.get("strategy_defaults", {})
    router_cfg = strategy_defaults.get("router", {}) if isinstance(strategy_defaults, dict) else {}
    if not isinstance(router_cfg, dict):
        router_cfg = {}

    prices_raw = snapshot.get("recent_prices", [])
    prices: list[float] = []
    if isinstance(prices_raw, list):
        for value in prices_raw:
            numeric = _as_float(value)
            if numeric is not None and numeric > 0:
                prices.append(float(numeric))

    sampling_minutes = max(1.0, _as_float(snapshot.get("sampling_minutes"), 5.0) or 5.0)
    latest_ts = _as_float(snapshot.get("snapshot_ts_epoch"), now_epoch) or now_epoch
    stale_seconds = max(60.0, _as_float(router_cfg.get("auto_max_regime_age_seconds"), 20 * 60) or (20 * 60))
    stale = (now_epoch - latest_ts) > stale_seconds

    timeframe_summary: list[dict[str, Any]] = []
    trend_votes = 0.0
    range_votes = 0.0
    breakout_votes = 0.0
    weakening_votes = 0.0
    weighted_agreement = 0.0
    total_weight = 0.0
    supported_count = 0
    supported_key_windows = False
    key_windows = {"4h", "24h"}

    for window_label, minutes in WINDOWS_MINUTES:
        points = int(round(minutes / sampling_minutes))
        points = max(points, 2)
        weight = 1.0
        if window_label == "4h":
            weight = 1.6
        elif window_label == "24h":
            weight = 1.9
        elif window_label in {"3d", "7d"}:
            weight = 1.2

        if len(prices) < points:
            timeframe_summary.append(
                {
                    "window": window_label,
                    "supported": False,
                    "sample": len(prices),
                    "required_sample": points,
                    "structure": "UNSUPPORTED",
                    "slope_pct": None,
                    "amplitude_pct": None,
                    "quality": "INSUFFICIENT",
                }
            )
            continue

        window = prices[-points:]
        first_price = window[0]
        last_price = window[-1]
        high_price = max(window)
        low_price = min(window)
        if first_price <= 0 or low_price <= 0:
            timeframe_summary.append(
                {
                    "window": window_label,
                    "supported": False,
                    "sample": points,
                    "required_sample": points,
                    "structure": "UNSUPPORTED",
                    "slope_pct": None,
                    "amplitude_pct": None,
                    "quality": "INSUFFICIENT",
                }
            )
            continue

        slope_pct = ((last_price - first_price) / first_price) * 100.0
        amplitude_pct = ((high_price - low_price) / ((high_price + low_price) / 2.0)) * 100.0
        abs_slope = abs(slope_pct)
        structure = "RANGE"
        if slope_pct >= 0.45:
            structure = "UPTREND"
        elif slope_pct <= -0.45:
            structure = "DOWNTREND"
        elif abs_slope >= 0.25:
            structure = "TRANSITION"

        quality = "GOOD"
        supported_count += 1
        if window_label in key_windows:
            supported_key_windows = True

        trend_component = 0.0
        if structure == "UPTREND":
            trend_component = 0.55 + _clamp(abs_slope / 2.0, 0.0, 0.35)
        elif structure == "DOWNTREND":
            weakening_votes += (0.50 + _clamp(abs_slope / 2.0, 0.0, 0.35)) * weight

        range_component = 0.0
        if structure == "RANGE":
            range_component = 0.52 + (0.20 if 0.4 <= amplitude_pct <= 7.0 else 0.0)

        breakout_component = 0.0
        if amplitude_pct >= 2.2 and abs_slope >= 0.32:
            breakout_component = 0.58 + _clamp((amplitude_pct - 2.2) / 5.0, 0.0, 0.30)

        top = max(trend_component, range_component, breakout_component)
        second = sorted([trend_component, range_component, breakout_component], reverse=True)[1]
        agreement = _clamp(top - second, 0.0, 1.0)

        trend_votes += trend_component * weight
        range_votes += range_component * weight
        breakout_votes += breakout_component * weight
        weighted_agreement += agreement * weight
        total_weight += weight

        timeframe_summary.append(
            {
                "window": window_label,
                "supported": True,
                "sample": points,
                "required_sample": points,
                "structure": structure,
                "slope_pct": round(slope_pct, 4),
                "amplitude_pct": round(amplitude_pct, 4),
                "quality": quality,
            }
        )

    if total_weight <= 0:
        return {
            "suggestedRegime": "MIXED_OR_UNCLEAR",
            "confidenceScore": 0.0,
            "confidenceLabel": "LOW",
            "stabilityScore": 0.0,
            "stabilityLabel": "LOW",
            "persistenceScore": 0.0,
            "persistenceLabel": "LOW",
            "structureScore": 0.0,
            "breakoutScore": 0.0,
            "bounceScore": 0.0,
            "structureBias": "UNCLEAR",
            "volatilityState": "UNKNOWN",
            "participationState": "LOW",
            "detectionSource": "regime_v2_runtime",
            "analysisAnchorEpoch": latest_ts,
            "explanation": "Insufficient recent price depth for Regime V2.",
            "insufficientData": True,
            "insufficientReasonCode": "insufficient_recent_prices",
            "insufficientReasonMessage": "Need more recent prices for 4h/24h windows.",
            "dataQuality": {
                "status": "INSUFFICIENT",
                "reason": "no_supported_windows",
                "supportedKeyWindows": False,
            },
            "timeframeSummary": timeframe_summary,
            "componentScores": {
                "trend_score": 0.0,
                "range_score": 0.0,
                "breakout_score": 0.0,
                "mixed_score": 100.0,
            },
        }

    trend_score = _clamp((trend_votes / total_weight) * 100.0, 0.0, 100.0)
    range_score = _clamp((range_votes / total_weight) * 100.0, 0.0, 100.0)
    breakout_score = _clamp((breakout_votes / total_weight) * 100.0, 0.0, 100.0)
    weakening_score = _clamp((weakening_votes / total_weight) * 100.0, 0.0, 100.0)
    agreement_score = _clamp((weighted_agreement / total_weight) * 100.0, 0.0, 100.0)

    returns = []
    for idx in range(1, len(prices)):
        prev = prices[idx - 1]
        if prev <= 0:
            continue
        returns.append((prices[idx] - prev) / prev)
    if returns:
        mean_ret = sum(returns) / len(returns)
        variance = sum((ret - mean_ret) ** 2 for ret in returns) / len(returns)
        ret_sigma = variance ** 0.5
    else:
        ret_sigma = 0.0
    stability_score = _clamp(100.0 - (ret_sigma * 4000.0), 0.0, 100.0)
    persistence_score = _clamp((0.55 * agreement_score) + (0.45 * trend_score), 0.0, 100.0)
    structure_score = _clamp((0.50 * trend_score) + (0.50 * range_score), 0.0, 100.0)
    bounce_score = _clamp(100.0 - breakout_score, 0.0, 100.0)

    quality_status = _quality_status(
        stale=stale,
        supported_key_windows=supported_key_windows,
        supported_count=supported_count,
    )
    quality_multiplier = 1.0
    if quality_status == "STALE":
        quality_multiplier = 0.62
    elif quality_status == "INSUFFICIENT":
        quality_multiplier = 0.58
    elif quality_status == "UNSUPPORTED_WINDOW":
        quality_multiplier = 0.55
    elif quality_status == "PARTIAL":
        quality_multiplier = 0.82

    confidence_raw = (
        (0.34 * agreement_score)
        + (0.26 * stability_score)
        + (0.24 * persistence_score)
        + (0.16 * structure_score)
    )
    confidence_score = _clamp(confidence_raw * quality_multiplier, 0.0, 100.0)

    structure_bias = "RANGE"
    if trend_score >= 62.0:
        structure_bias = "BULLISH_TREND"
    elif weakening_score >= 60.0:
        structure_bias = "WEAKENING_TREND"
    elif breakout_score >= 64.0:
        structure_bias = "BREAKOUT"
    elif confidence_score < 52.0:
        structure_bias = "UNCLEAR"

    volatility_state = "NORMAL"
    if breakout_score >= 72.0:
        volatility_state = "EXPANDING"
    if ret_sigma >= 0.02:
        volatility_state = "EXTREME"
    elif ret_sigma <= 0.003:
        volatility_state = "LOW"

    spread_bps = _as_float(snapshot.get("spread_bps"), 0.0) or 0.0
    trade_count = _as_float(snapshot.get("trade_count"), 0.0) or 0.0
    participation_state = "NORMAL"
    if trade_count < 6 or spread_bps > 180:
        participation_state = "LOW"
    elif trade_count > 40 and spread_bps < 60:
        participation_state = "HIGH"

    suggested_regime = "MEAN_REVERSION_FRIENDLY"
    if quality_status in {"STALE", "INSUFFICIENT", "UNSUPPORTED_WINDOW"}:
        suggested_regime = "MIXED_OR_UNCLEAR"
    elif confidence_score < 62.0:
        suggested_regime = "MIXED_OR_UNCLEAR"
    elif stability_score < 38.0 and participation_state == "LOW":
        suggested_regime = "HIGH_RISK_UNSTABLE"
    elif breakout_score >= 70.0 and confidence_score >= 74.0 and stability_score >= 52.0:
        suggested_regime = "BREAKOUT_EXPANSION"
    elif weakening_score >= 64.0:
        suggested_regime = "TREND_WEAKENING"
    elif trend_score >= 60.0 and persistence_score >= 58.0:
        suggested_regime = "TREND_CONTINUATION"
    elif range_score >= 54.0:
        suggested_regime = "MEAN_REVERSION_FRIENDLY"
    else:
        suggested_regime = "MIXED_OR_UNCLEAR"

    return {
        "suggestedRegime": suggested_regime,
        "confidenceScore": round(confidence_score, 3),
        "confidenceLabel": _label(confidence_score),
        "stabilityScore": round(stability_score, 3),
        "stabilityLabel": _label(stability_score),
        "persistenceScore": round(persistence_score, 3),
        "persistenceLabel": _label(persistence_score),
        "structureScore": round(structure_score, 3),
        "breakoutScore": round(breakout_score, 3),
        "bounceScore": round(bounce_score, 3),
        "structureBias": structure_bias,
        "volatilityState": volatility_state,
        "participationState": participation_state,
        "detectionSource": "regime_v2_runtime",
        "analysisAnchorEpoch": latest_ts,
        "explanation": (
            f"{suggested_regime.replace('_', ' ')} | "
            f"confidence={confidence_score:.1f} stability={stability_score:.1f} "
            f"persistence={persistence_score:.1f} quality={quality_status}"
        ),
        "insufficientData": quality_status in {"STALE", "INSUFFICIENT", "UNSUPPORTED_WINDOW"},
        "insufficientReasonCode": (
            "stale_or_unsupported_data"
            if quality_status in {"STALE", "UNSUPPORTED_WINDOW"}
            else ("insufficient_window_depth" if quality_status == "INSUFFICIENT" else None)
        ),
        "insufficientReasonMessage": (
            "Regime V2 fell back due to stale/unsupported key windows."
            if quality_status in {"STALE", "UNSUPPORTED_WINDOW"}
            else ("Regime V2 needs deeper history for key windows." if quality_status == "INSUFFICIENT" else None)
        ),
        "dataQuality": {
            "status": quality_status,
            "reason": "window_coverage_and_freshness",
            "supportedKeyWindows": supported_key_windows,
            "supportedWindowCount": supported_count,
            "stale": stale,
        },
        "timeframeSummary": timeframe_summary,
        "componentScores": {
            "trend_score": round(trend_score, 3),
            "range_score": round(range_score, 3),
            "breakout_score": round(breakout_score, 3),
            "mixed_score": round(_clamp(100.0 - agreement_score, 0.0, 100.0), 3),
            "weakening_score": round(weakening_score, 3),
        },
    }

