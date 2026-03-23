from __future__ import annotations

from typing import Any

from strategy.regime import detect_regime


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

LEGACY_TO_V2 = {
    "range": "MEAN_REVERSION_FRIENDLY",
    "accumulation": "ACCUMULATION",
    "trend_up": "TREND_CONTINUATION",
    "spike": "BREAKOUT_EXPANSION",
    "trend_down": "SLOW_BLEED",
    "dump": "CAPITULATION_PANIC",
    "chop": "MIXED_OR_UNCLEAR",
    "unknown": "MIXED_OR_UNCLEAR",
}

REGIME_LABELS = {
    "MEAN_REVERSION_FRIENDLY": "Mean-Reversion-Friendly Range",
    "TREND_CONTINUATION": "Trend Continuation / Pullback",
    "BREAKOUT_EXPANSION": "Breakout Expansion",
    "TREND_WEAKENING": "Trend Weakening",
    "HIGH_RISK_UNSTABLE": "High-Risk Unstable / Whipsaw",
    "ACCUMULATION": "Accumulation",
    "DISTRIBUTION": "Distribution",
    "LIQUIDITY_SWEEP_REVERSAL": "Liquidity Sweep Reversal",
    "VOLATILITY_COMPRESSION": "Volatility Compression / Squeeze",
    "SLOW_BLEED": "Slow Bleed / Downtrend Drift",
    "CAPITULATION_PANIC": "Capitulation / Panic Flush",
    "LOW_PARTICIPATION_DEAD_MARKET": "Low-Participation Dead Market",
    "MIXED_OR_UNCLEAR": "Mixed / Unclear",
}


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


def _regime_label(code: str) -> str:
    return REGIME_LABELS.get(str(code or "").strip().upper(), "Mixed / Unclear")


def _router_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    strategy_defaults = cfg.get("strategy_defaults", {})
    router_cfg = strategy_defaults.get("router", {}) if isinstance(strategy_defaults, dict) else {}
    if not isinstance(router_cfg, dict):
        return {}
    return router_cfg


def _threshold(router_cfg: dict[str, Any], key: str, fallback: float) -> float:
    thresholds = router_cfg.get("regime_v2_thresholds", {})
    if isinstance(thresholds, dict):
        parsed = _as_float(thresholds.get(key))
        if parsed is not None:
            if 0 <= parsed <= 1.0:
                return float(parsed)
            return float(parsed / 100.0)
    parsed = _as_float(router_cfg.get(key))
    if parsed is not None:
        if 0 <= parsed <= 1.0:
            return float(parsed)
        return float(parsed / 100.0)
    return fallback


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
    router_cfg = _router_cfg(cfg)

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
    weighted_amplitude_sum = 0.0
    weighted_amplitude_weight = 0.0
    supported_count = 0
    key_windows = {"4h", "24h"}
    supported_key_windows_seen: set[str] = set()

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
                    "structure_label": "Unsupported",
                    "structure_score": 0.0,
                    "stability_score": 0.0,
                    "persistence_score": 0.0,
                    "breakout_score": 0.0,
                    "bounce_score": 0.0,
                    "slope_pct": None,
                    "amplitude_pct": None,
                    "median_high_zone": None,
                    "median_low_zone": None,
                    "quality": "INSUFFICIENT",
                    "quality_status": "INSUFFICIENT",
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
                    "structure_label": "Unsupported",
                    "structure_score": 0.0,
                    "stability_score": 0.0,
                    "persistence_score": 0.0,
                    "breakout_score": 0.0,
                    "bounce_score": 0.0,
                    "slope_pct": None,
                    "amplitude_pct": None,
                    "median_high_zone": None,
                    "median_low_zone": None,
                    "quality": "INSUFFICIENT",
                    "quality_status": "INSUFFICIENT",
                }
            )
            continue

        slope_pct = ((last_price - first_price) / first_price) * 100.0
        amplitude_pct = ((high_price - low_price) / ((high_price + low_price) / 2.0)) * 100.0
        window_returns = []
        for idx in range(1, len(window)):
            prev_px = window[idx - 1]
            if prev_px <= 0:
                continue
            window_returns.append((window[idx] - prev_px) / prev_px)
        if window_returns:
            mean_window_ret = sum(window_returns) / len(window_returns)
            ret_sigma = (
                sum((ret - mean_window_ret) ** 2 for ret in window_returns) / len(window_returns)
            ) ** 0.5
        else:
            ret_sigma = 0.0
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
            supported_key_windows_seen.add(window_label)

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
        weighted_amplitude_sum += amplitude_pct * weight
        weighted_amplitude_weight += weight

        timeframe_summary.append(
            {
                "window": window_label,
                "supported": True,
                "sample": points,
                "required_sample": points,
                "structure": structure,
                "structure_label": structure.title(),
                "structure_score": round(max(trend_component, range_component, breakout_component) * 100.0, 3),
                "stability_score": round(_clamp(100.0 - (ret_sigma * 4000.0), 0.0, 100.0), 3),
                "persistence_score": round(agreement * 100.0, 3),
                "breakout_score": round(breakout_component * 100.0, 3),
                "bounce_score": round(_clamp(100.0 - (breakout_component * 100.0), 0.0, 100.0), 3),
                "slope_pct": round(slope_pct, 4),
                "amplitude_pct": round(amplitude_pct, 4),
                "median_high_zone": round((high_price + ((high_price + low_price) / 2.0)) / 2.0, 8),
                "median_low_zone": round((low_price + ((high_price + low_price) / 2.0)) / 2.0, 8),
                "quality": quality,
                "quality_status": quality,
            }
        )

    if total_weight <= 0:
        return {
            "suggestedRegime": "MIXED_OR_UNCLEAR",
            "suggestedRegimeLabel": _regime_label("MIXED_OR_UNCLEAR"),
            "regimeTier": "TIER_1",
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
    weighted_amplitude_pct = (
        weighted_amplitude_sum / weighted_amplitude_weight
        if weighted_amplitude_weight > 0
        else 0.0
    )
    supported_key_windows = key_windows.issubset(supported_key_windows_seen)

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

    quality_score = _clamp(quality_multiplier, 0.0, 1.0)
    confidence_score_norm = _clamp(confidence_score / 100.0, 0.0, 1.0)
    stability_score_norm = _clamp(stability_score / 100.0, 0.0, 1.0)
    persistence_score_norm = _clamp(persistence_score / 100.0, 0.0, 1.0)
    trend_score_norm = _clamp(trend_score / 100.0, 0.0, 1.0)
    range_score_norm = _clamp(range_score / 100.0, 0.0, 1.0)
    breakout_score_norm = _clamp(breakout_score / 100.0, 0.0, 1.0)
    weakening_score_norm = _clamp(weakening_score / 100.0, 0.0, 1.0)
    compression_score_norm = _clamp(1.0 - min((ret_sigma * 2200.0), 1.0), 0.0, 1.0)
    dead_market_score = _clamp(
        (0.55 * compression_score_norm)
        + (0.25 * (1.0 if participation_state == "LOW" else 0.25))
        + (0.20 * (1.0 - min(abs(agreement_score - 50.0) / 50.0, 1.0))),
        0.0,
        1.0,
    )
    accumulation_score = _clamp((0.60 * range_score_norm) + (0.40 * compression_score_norm), 0.0, 1.0)
    distribution_score = _clamp((0.60 * weakening_score_norm) + (0.40 * (1.0 - persistence_score_norm)), 0.0, 1.0)
    capitulation_score = _clamp(
        (0.45 * _clamp((ret_sigma * 3200.0), 0.0, 1.0))
        + (0.35 * weakening_score_norm)
        + (0.20 * (1.0 - stability_score_norm)),
        0.0,
        1.0,
    )
    liquidity_sweep_score = _clamp(
        (0.50 * breakout_score_norm)
        + (0.30 * range_score_norm)
        + (0.20 * _clamp((100.0 - spread_bps) / 100.0, 0.0, 1.0)),
        0.0,
        1.0,
    )

    min_conf = _threshold(router_cfg, "regime_v2_min_confidence", 0.62)
    min_stability = _threshold(router_cfg, "regime_v2_min_stability", 0.58)
    min_persistence = _threshold(router_cfg, "regime_v2_min_persistence", 0.58)
    min_trend = _threshold(router_cfg, "regime_v2_trend_min", 0.67)
    min_breakout = _threshold(router_cfg, "regime_v2_breakout_min", 0.82)
    min_breakout_conf = _threshold(router_cfg, "regime_v2_breakout_min_confidence", 0.80)

    suggested_regime = "MIXED_OR_UNCLEAR"
    regime_tier = "TIER_1"
    if quality_status in {"STALE", "INSUFFICIENT", "UNSUPPORTED_WINDOW"}:
        suggested_regime = "MIXED_OR_UNCLEAR"
    elif (
        breakout_score_norm >= min_breakout
        and confidence_score_norm >= min_breakout_conf
        and stability_score_norm >= min_stability
        and persistence_score_norm >= min_persistence
    ):
        suggested_regime = "BREAKOUT_EXPANSION"
    elif (
        trend_score_norm >= min_trend
        and confidence_score_norm >= _threshold(router_cfg, "regime_v2_trend_min_confidence", 0.70)
        and stability_score_norm >= min_stability
        and persistence_score_norm >= min_persistence
    ):
        suggested_regime = "TREND_CONTINUATION"
    elif (
        range_score_norm >= _threshold(router_cfg, "regime_v2_range_min", 0.58)
        and confidence_score_norm >= min_conf
    ):
        suggested_regime = "MEAN_REVERSION_FRIENDLY"
    else:
        regime_tier = "TIER_2"
        if weakening_score_norm >= _threshold(router_cfg, "regime_v2_trend_weakening_min", 0.62):
            suggested_regime = "TREND_WEAKENING"
        elif (
            stability_score_norm < _threshold(router_cfg, "regime_v2_low_stability", 0.48)
            and persistence_score_norm < _threshold(router_cfg, "regime_v2_low_persistence", 0.48)
        ):
            suggested_regime = "HIGH_RISK_UNSTABLE"
        elif dead_market_score >= _threshold(router_cfg, "regime_v2_dead_market_min", 0.62):
            suggested_regime = "LOW_PARTICIPATION_DEAD_MARKET"
        elif weakening_score_norm >= _threshold(router_cfg, "regime_v2_slow_bleed_min", 0.58):
            suggested_regime = "SLOW_BLEED"
        else:
            regime_tier = "TIER_3"
            if accumulation_score >= _threshold(router_cfg, "regime_v2_accumulation_min", 0.66):
                suggested_regime = "ACCUMULATION"
            elif distribution_score >= _threshold(router_cfg, "regime_v2_distribution_min", 0.66):
                suggested_regime = "DISTRIBUTION"
            elif liquidity_sweep_score >= _threshold(router_cfg, "regime_v2_liquidity_sweep_min", 0.72):
                suggested_regime = "LIQUIDITY_SWEEP_REVERSAL"
            elif compression_score_norm >= _threshold(router_cfg, "regime_v2_compression_min", 0.70):
                suggested_regime = "VOLATILITY_COMPRESSION"
            elif capitulation_score >= _threshold(router_cfg, "regime_v2_capitulation_min", 0.74):
                suggested_regime = "CAPITULATION_PANIC"
            else:
                suggested_regime = "MIXED_OR_UNCLEAR"

    return {
        "suggestedRegime": suggested_regime,
        "suggestedRegimeLabel": _regime_label(suggested_regime),
        "regimeTier": regime_tier,
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
            f"{_regime_label(suggested_regime)} | "
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
            "dataQualityScore": round(quality_score, 6),
        },
        "timeframeSummary": timeframe_summary,
        "componentScores": {
            "trend_score": round(trend_score, 3),
            "range_score": round(range_score, 3),
            "breakout_score": round(breakout_score, 3),
            "mixed_score": round(_clamp(100.0 - agreement_score, 0.0, 100.0), 3),
            "weakening_score": round(weakening_score, 3),
        },
        "primaryScores": {
            "range_score": round(range_score_norm, 6),
            "trend_pullback_score": round(trend_score_norm, 6),
            "breakout_score": round(breakout_score_norm, 6),
            "unstable_score": round(
                _clamp((1.0 - stability_score_norm) * 0.5 + (1.0 - persistence_score_norm) * 0.5, 0.0, 1.0),
                6,
            ),
            "bleed_score": round(weakening_score_norm, 6),
        },
        "qualityAnalytics": {
            "data_quality_score": round(quality_score, 6),
            "supported_window_flags": {row["window"]: bool(row.get("supported")) for row in timeframe_summary},
            "freshness_ok": not stale,
            "spread_quality": round(_clamp((100.0 - spread_bps) / 100.0, 0.0, 1.0), 6),
            "source_strength": 1.0,
        },
        "volatilityAnalytics": {
            "atr_norm": round((weighted_amplitude_pct / 100.0), 8),
            "expansion_ratio": round(_clamp(breakout_score_norm * 1.3, 0.0, 1.0), 6),
            "compression_score": round(compression_score_norm, 6),
            "impulse_strength": round(_clamp(trend_score_norm, 0.0, 1.0), 6),
            "bounce_strength_score": round(_clamp(1.0 - breakout_score_norm, 0.0, 1.0), 6),
            "volatility_state": volatility_state,
        },
        "confidenceAnalytics": {
            "stability_score": round(stability_score_norm, 6),
            "persistence_score": round(persistence_score_norm, 6),
            "agreement_score": round(_clamp(agreement_score / 100.0, 0.0, 1.0), 6),
            "unified_confidence_score": round(_clamp(confidence_score / 100.0, 0.0, 1.0), 6),
        },
    }


def evaluate_regime_unified(
    *,
    snapshot: dict[str, Any],
    now_epoch: float,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg or {}
    v2 = evaluate_regime_v2(snapshot=snapshot, now_epoch=now_epoch, cfg=cfg)
    if not isinstance(v2, dict):
        v2 = {}

    insufficient = bool(v2.get("insufficientData", False))
    confidence_score = float(v2.get("confidenceScore", 0.0) or 0.0)
    suggested = str(v2.get("suggestedRegime") or "").strip().upper()
    if not suggested:
        insufficient = True

    # Keep V2 primary; only use legacy regime as conservative fallback context.
    if insufficient or confidence_score < 35.0:
        try:
            legacy = str(detect_regime(snapshot, cfg.get("market_regime", {})) or "unknown").strip().lower()
        except Exception:
            legacy = "unknown"
        legacy_mapped = LEGACY_TO_V2.get(legacy, "MIXED_OR_UNCLEAR")
        if not suggested or suggested == "MIXED_OR_UNCLEAR":
            v2["suggestedRegime"] = legacy_mapped
        v2["legacyRegime"] = legacy
        v2["legacyMappedRegime"] = legacy_mapped
        if "confidenceScore" not in v2 or confidence_score <= 0:
            v2["confidenceScore"] = 32.0
            v2["confidenceLabel"] = _label(32.0)

    v2.setdefault("detectionSource", "regime_v2_runtime")
    v2.setdefault("analysisAnchorEpoch", now_epoch)
    if "suggestedRegimeLabel" not in v2:
        v2["suggestedRegimeLabel"] = _regime_label(str(v2.get("suggestedRegime") or "MIXED_OR_UNCLEAR"))
    return v2
