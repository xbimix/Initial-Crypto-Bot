from __future__ import annotations

from data.indicator_engine import calculate_bundle


def classify_volatility_state(volatility_score: float | None) -> str:
    if volatility_score is None:
        return "LOW"
    if volatility_score >= 85:
        return "EXTREME"
    if volatility_score >= 60:
        return "EXPANDING"
    if volatility_score >= 30:
        return "NORMAL"
    return "LOW"


def label_volatility_state(state: str) -> str:
    mapping = {
        "LOW": "Low Volatility",
        "NORMAL": "Normal Volatility",
        "EXPANDING": "Expanding",
        "EXTREME": "Extreme",
    }
    return mapping.get(state, "Normal Volatility")


def analyze_volatility(
    candles: list[dict],
    *,
    stale: bool = False,
    supported: bool = True,
) -> dict:
    indicators = calculate_bundle(
        candles,
        min_points=30,
        stale=stale,
        supported=supported,
    )
    atr = indicators.get("atr")
    rv = indicators.get("return_volatility")
    momentum = indicators.get("momentum")
    expansion = indicators.get("expansion_score")
    compression = indicators.get("compression_score")

    impulse_strength = None
    if momentum is not None and rv is not None:
        impulse_strength = min(100.0, max(0.0, abs(momentum) * 2500 + rv * 2500))

    bounce_context = None
    if momentum is not None:
        bounce_context = min(100.0, max(0.0, (1.0 - max(momentum, -0.06) / 0.06) * 50.0))
    liquidity_quality = 75.0

    components = {
        "atr_normalized": atr,
        "expansion_ratio": expansion,
        "compression_score": compression,
        "impulse_strength": impulse_strength,
        "bounce_context": bounce_context,
        "liquidity_market_quality": liquidity_quality,
    }
    numeric_components = [v for v in components.values() if isinstance(v, (int, float))]
    volatility_score = (
        sum(float(v) for v in numeric_components) / len(numeric_components)
        if numeric_components
        else None
    )
    state = classify_volatility_state(volatility_score)
    quality = indicators.get("data_quality", {})
    insufficient = quality.get("status") in {"INSUFFICIENT", "UNSUPPORTED_WINDOW"}
    confidence = 85.0 if quality.get("status") == "GOOD" else 60.0 if quality.get("status") == "PARTIAL" else 35.0
    return {
        "volatility_state": state,
        "volatility_label": label_volatility_state(state),
        "volatility_score": None if volatility_score is None else max(0.0, min(100.0, float(volatility_score))),
        "components": components,
        "confidence": confidence,
        "insufficient_data": insufficient,
        "data_quality": quality,
    }

