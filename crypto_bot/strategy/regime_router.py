from __future__ import annotations

import time
from typing import Any

from utils.token_regimes import (
    TOKEN_REGIME_BREAKOUT_MOMENTUM,
    TOKEN_REGIME_MEAN_REVERSION,
    TOKEN_REGIME_OBSERVE_ONLY,
    TOKEN_REGIME_TREND_PULLBACK,
    normalize_symbol,
    normalize_token_regime,
)

STRATEGY_MEAN_REVERSION = "mean_reversion"
STRATEGY_VOLATILITY_SCALPER = "volatility_scalper"
STRATEGY_TREND_PULLBACK = "trend_pullback"
STRATEGY_BREAKOUT_MOMENTUM = "breakout_momentum"
STRATEGY_OBSERVE_ONLY = "observe_only"

AUTO_DEFAULT_MIN_CONFIDENCE_SCORE = 68.0
AUTO_DEFAULT_MIN_CONFIRMATIONS = 2
AUTO_DEFAULT_MIN_STABILITY_SCORE = 58.0
AUTO_DEFAULT_MIN_PERSISTENCE_SCORE = 58.0
AUTO_DEFAULT_MAX_ROUTE_AGE_SECONDS = 15 * 60

SUGGESTED_REGIME_MEAN_REVERSION = "MEAN_REVERSION_FRIENDLY"
SUGGESTED_REGIME_TREND = "TREND_CONTINUATION"
SUGGESTED_REGIME_BREAKOUT = "BREAKOUT_EXPANSION"
SUGGESTED_REGIME_TREND_WEAKENING = "TREND_WEAKENING"
SUGGESTED_REGIME_HIGH_RISK_UNSTABLE = "HIGH_RISK_UNSTABLE"
SUGGESTED_REGIME_MIXED = "MIXED_OR_UNCLEAR"

SUGGESTED_REGIME_TO_STRATEGY = {
    SUGGESTED_REGIME_MEAN_REVERSION: STRATEGY_MEAN_REVERSION,
    SUGGESTED_REGIME_TREND: STRATEGY_TREND_PULLBACK,
    SUGGESTED_REGIME_BREAKOUT: STRATEGY_BREAKOUT_MOMENTUM,
    SUGGESTED_REGIME_TREND_WEAKENING: STRATEGY_MEAN_REVERSION,
    SUGGESTED_REGIME_HIGH_RISK_UNSTABLE: STRATEGY_MEAN_REVERSION,
    SUGGESTED_REGIME_MIXED: STRATEGY_MEAN_REVERSION,
}

RAW_REGIME_TO_SUGGESTED = {
    "range": SUGGESTED_REGIME_MEAN_REVERSION,
    "accumulation": SUGGESTED_REGIME_MEAN_REVERSION,
    "trend_up": SUGGESTED_REGIME_TREND,
    "spike": SUGGESTED_REGIME_BREAKOUT,
    "chop": SUGGESTED_REGIME_MIXED,
    "dump": SUGGESTED_REGIME_MIXED,
    "trend_down": SUGGESTED_REGIME_MIXED,
    "unknown": SUGGESTED_REGIME_MIXED,
}


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:  # NaN guard
        return None
    return parsed


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
    return default


def _normalized_confidence_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip().upper()
    if raw in {"LOW", "MEDIUM", "HIGH"}:
        return raw
    return None


def _confidence_from_label(label: str | None) -> float | None:
    if label == "HIGH":
        return 78.0
    if label == "MEDIUM":
        return 56.0
    if label == "LOW":
        return 32.0
    return None


def _is_insufficient(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _confidence_label_from_score(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 72:
        return "HIGH"
    if score >= 48:
        return "MEDIUM"
    return "LOW"


def _normalize_confidence_score(value: Any) -> float | None:
    score = _as_float(value)
    if score is None:
        return None
    if 0 <= score <= 1.0:
        score = score * 100.0
    return max(0.0, min(score, 100.0))


def _router_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    strategy_defaults = cfg.get("strategy_defaults", {})
    if not isinstance(strategy_defaults, dict):
        return {}
    router = strategy_defaults.get("router", {})
    if not isinstance(router, dict):
        return {}
    return router


def _auto_min_confidence_score(cfg: dict[str, Any]) -> float:
    router = _router_cfg(cfg)
    configured = _normalize_confidence_score(router.get("auto_min_confidence"))
    if configured is None:
        return AUTO_DEFAULT_MIN_CONFIDENCE_SCORE
    return configured


def _auto_min_confirmations(cfg: dict[str, Any]) -> int:
    router = _router_cfg(cfg)
    raw = router.get("auto_min_confirmations", router.get("confirmations_required"))
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        value = AUTO_DEFAULT_MIN_CONFIRMATIONS
    return max(value, 1)


def _auto_use_multitimeframe_advisory(cfg: dict[str, Any]) -> bool:
    router = _router_cfg(cfg)
    return _as_bool(router.get("auto_use_multitimeframe_advisory"), False)


def _auto_min_stability_score(cfg: dict[str, Any]) -> float:
    router = _router_cfg(cfg)
    configured = _normalize_confidence_score(router.get("auto_min_stability"))
    if configured is None:
        return AUTO_DEFAULT_MIN_STABILITY_SCORE
    return configured


def _auto_min_persistence_score(cfg: dict[str, Any]) -> float:
    router = _router_cfg(cfg)
    configured = _normalize_confidence_score(router.get("auto_min_persistence"))
    if configured is None:
        return AUTO_DEFAULT_MIN_PERSISTENCE_SCORE
    return configured


def _auto_max_route_age_seconds(cfg: dict[str, Any]) -> float:
    router = _router_cfg(cfg)
    age = _as_float(router.get("auto_max_route_age_seconds"))
    if age is None or age <= 0:
        return AUTO_DEFAULT_MAX_ROUTE_AGE_SECONDS
    return max(age, 60.0)


def _extract_regime_advisory(snapshot: dict[str, Any]) -> dict[str, Any]:
    advisory = snapshot.get("regime_advisory")
    if not isinstance(advisory, dict):
        advisory = {}

    suggested = advisory.get("suggestedRegime")
    if not isinstance(suggested, str):
        suggested = advisory.get("suggested_regime")
    if not isinstance(suggested, str):
        suggested = advisory.get("detectedRegime")
    if not isinstance(suggested, str):
        suggested = advisory.get("detected_regime")
    if not isinstance(suggested, str):
        suggested = snapshot.get("detected_regime")
    if not isinstance(suggested, str):
        suggested = snapshot.get("detectedRegime")

    confidence_score = _normalize_confidence_score(advisory.get("confidenceScore"))
    if confidence_score is None:
        confidence_score = _normalize_confidence_score(advisory.get("confidence_score"))
    if confidence_score is None:
        confidence_score = _normalize_confidence_score(snapshot.get("detected_regime_confidence"))
    if confidence_score is None:
        confidence_score = _normalize_confidence_score(snapshot.get("detectedRegimeConfidence"))

    confidence_label = _normalized_confidence_label(advisory.get("confidenceLabel"))
    if confidence_label is None:
        confidence_label = _normalized_confidence_label(advisory.get("confidence_label"))
    if confidence_label is None:
        confidence_label = _normalized_confidence_label(snapshot.get("detected_regime_confidence_label"))
    if confidence_label is None:
        confidence_label = _normalized_confidence_label(snapshot.get("detectedRegimeConfidenceLabel"))

    if confidence_score is None:
        confidence_score = _confidence_from_label(confidence_label)
    if confidence_label is None:
        confidence_label = _confidence_label_from_score(confidence_score)

    insufficient_data = _is_insufficient(advisory.get("insufficientData"))
    if not insufficient_data:
        insufficient_data = _is_insufficient(advisory.get("insufficient_data"))

    detection_source = advisory.get("detectionSource")
    if not isinstance(detection_source, str):
        detection_source = advisory.get("detection_source")
    if not isinstance(detection_source, str):
        detection_source = "advisory_multitimeframe"

    detection_timestamp_epoch = _as_float(advisory.get("analysisAnchorEpoch"))
    if detection_timestamp_epoch is None:
        detection_timestamp_epoch = _as_float(advisory.get("analysis_anchor_epoch"))
    if detection_timestamp_epoch is None:
        detection_timestamp_epoch = _as_float(advisory.get("detectionTimestampEpoch"))
    if detection_timestamp_epoch is None:
        detection_timestamp_epoch = _as_float(advisory.get("detection_timestamp_epoch"))
    if detection_timestamp_epoch is None:
        detection_timestamp_epoch = _as_float(snapshot.get("detected_regime_timestamp_epoch"))

    stability_score = _normalize_confidence_score(advisory.get("stabilityScore"))
    if stability_score is None:
        stability_score = _normalize_confidence_score(advisory.get("stability_score"))
    persistence_score = _normalize_confidence_score(advisory.get("persistenceScore"))
    if persistence_score is None:
        persistence_score = _normalize_confidence_score(advisory.get("persistence_score"))

    data_quality = advisory.get("dataQuality")
    if not isinstance(data_quality, dict):
        data_quality = advisory.get("data_quality")
    if not isinstance(data_quality, dict):
        data_quality = {}

    data_quality_status = data_quality.get("status")
    if not isinstance(data_quality_status, str):
        data_quality_status = "UNKNOWN"
    data_quality_status = data_quality_status.strip().upper() or "UNKNOWN"
    supported_key_windows = _as_bool(data_quality.get("supportedKeyWindows"), True)
    if "supported_key_windows" in data_quality:
        supported_key_windows = _as_bool(data_quality.get("supported_key_windows"), supported_key_windows)

    normalized_suggested = ""
    if isinstance(suggested, str):
        normalized_suggested = suggested.strip().upper()

    return {
        "suggested_regime": normalized_suggested or None,
        "confidence_score": confidence_score,
        "confidence_label": confidence_label,
        "insufficient_data": insufficient_data,
        "insufficient_reason": "snapshot_advisory_insufficient" if insufficient_data else None,
        "detection_source": detection_source.strip().lower(),
        "detection_timestamp_epoch": detection_timestamp_epoch,
        "stability_score": stability_score,
        "persistence_score": persistence_score,
        "data_quality_status": data_quality_status,
        "supported_key_windows": supported_key_windows,
    }


def _configured_regime(cfg: dict[str, Any], symbol: str) -> str:
    token_regimes = cfg.get("token_regimes", {})
    if not isinstance(token_regimes, dict):
        return TOKEN_REGIME_MEAN_REVERSION

    symbol_key = normalize_symbol(symbol)
    if not symbol_key:
        return TOKEN_REGIME_MEAN_REVERSION

    raw = token_regimes.get(symbol_key)
    return normalize_token_regime(raw, default=TOKEN_REGIME_MEAN_REVERSION)


def _extract_shadow_advisory(
    *,
    symbol: str,
    shadow_state: dict[str, Any],
    min_confirmations: int,
) -> dict[str, Any]:
    symbol_key = normalize_symbol(symbol)
    if not symbol_key or not isinstance(shadow_state, dict):
        return {
            "suggested_regime": None,
            "confidence_score": None,
            "confidence_label": None,
            "insufficient_data": True,
            "insufficient_reason": "missing_shadow_state",
            "detection_source": "runtime_shadow",
            "detection_timestamp_epoch": None,
            "stability_score": None,
            "persistence_score": None,
            "data_quality_status": "UNKNOWN",
            "supported_key_windows": False,
        }

    row = shadow_state.get(symbol_key)
    if not isinstance(row, dict):
        return {
            "suggested_regime": None,
            "confidence_score": None,
            "confidence_label": None,
            "insufficient_data": True,
            "insufficient_reason": "missing_shadow_state",
            "detection_source": "runtime_shadow",
            "detection_timestamp_epoch": None,
            "stability_score": None,
            "persistence_score": None,
            "data_quality_status": "UNKNOWN",
            "supported_key_windows": False,
        }

    confirmations = _as_float(row.get("confirmations"))
    if confirmations is None or int(confirmations) < min_confirmations:
        return {
            "suggested_regime": None,
            "confidence_score": _normalize_confidence_score(row.get("confidence")),
            "confidence_label": _confidence_label_from_score(
                _normalize_confidence_score(row.get("confidence"))
            ),
            "insufficient_data": True,
            "insufficient_reason": "insufficient_shadow_confirmations",
            "detection_source": "runtime_shadow",
            "detection_timestamp_epoch": _as_float(row.get("last_update_ts")),
            "stability_score": _normalize_confidence_score(row.get("confidence")),
            "persistence_score": _normalize_confidence_score(row.get("confidence")),
            "data_quality_status": "PARTIAL",
            "supported_key_windows": True,
        }

    stable = str(
        row.get("stable_regime")
        or row.get("candidate_regime")
        or "unknown"
    ).strip().lower()
    suggested = RAW_REGIME_TO_SUGGESTED.get(stable, SUGGESTED_REGIME_MIXED)
    confidence_score = _normalize_confidence_score(row.get("confidence"))
    confidence_label = _confidence_label_from_score(confidence_score)

    return {
        "suggested_regime": suggested,
        "confidence_score": confidence_score,
        "confidence_label": confidence_label,
        "insufficient_data": False,
        "insufficient_reason": None,
        "detection_source": "runtime_shadow",
        "detection_timestamp_epoch": _as_float(row.get("last_update_ts")),
        "stability_score": confidence_score,
        "persistence_score": confidence_score,
        "data_quality_status": "PARTIAL",
        "supported_key_windows": True,
    }


def _normalize_default_strategy(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw == STRATEGY_VOLATILITY_SCALPER:
        return STRATEGY_VOLATILITY_SCALPER
    if raw == STRATEGY_TREND_PULLBACK:
        return STRATEGY_TREND_PULLBACK
    if raw == STRATEGY_BREAKOUT_MOMENTUM:
        return STRATEGY_BREAKOUT_MOMENTUM
    if raw == STRATEGY_OBSERVE_ONLY:
        return STRATEGY_OBSERVE_ONLY
    return STRATEGY_MEAN_REVERSION


def resolve_entry_route(
    *,
    cfg: dict[str, Any],
    symbol: str,
    snapshot: dict[str, Any],
    default_strategy: str,
    shadow_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    configured_regime = _configured_regime(cfg, symbol)

    result = {
        "configured_regime": configured_regime,
        "detected_regime": None,
        "suggested_regime_v2": None,
        "detected_regime_confidence": None,
        "detected_regime_confidence_label": None,
        "detected_regime_stability": None,
        "detected_regime_persistence": None,
        "regime_data_quality_status": "UNKNOWN",
        "regime_key_windows_supported": False,
        "detection_source": "configured_manual",
        "detection_timestamp_epoch": None,
        # AUTO and unclear cases must degrade to frozen mean reversion by default.
        "effective_strategy": STRATEGY_MEAN_REVERSION,
        "effective_route": STRATEGY_MEAN_REVERSION,
        "route_eval_ts": _as_float(snapshot.get("router_eval_ts")) or time.time(),
        "regime_eval_ts": _as_float(snapshot.get("regime_eval_ts")),
        "auto_fallback_reason": None,
        "fallback_reason": None,
    }

    if configured_regime == TOKEN_REGIME_OBSERVE_ONLY:
        result["effective_strategy"] = STRATEGY_OBSERVE_ONLY
        result["effective_route"] = STRATEGY_OBSERVE_ONLY
        return result

    if configured_regime == TOKEN_REGIME_TREND_PULLBACK:
        result["effective_strategy"] = STRATEGY_TREND_PULLBACK
        result["effective_route"] = STRATEGY_TREND_PULLBACK
        return result

    if configured_regime == TOKEN_REGIME_BREAKOUT_MOMENTUM:
        result["effective_strategy"] = STRATEGY_BREAKOUT_MOMENTUM
        result["effective_route"] = STRATEGY_BREAKOUT_MOMENTUM
        return result

    # Preserve default behavior for explicit manual mean-reversion mode.
    if configured_regime == TOKEN_REGIME_MEAN_REVERSION:
        result["effective_strategy"] = STRATEGY_MEAN_REVERSION
        result["effective_route"] = STRATEGY_MEAN_REVERSION
        return result

    min_confidence_score = _auto_min_confidence_score(cfg)
    min_stability_score = _auto_min_stability_score(cfg)
    min_persistence_score = _auto_min_persistence_score(cfg)
    min_confirmations = _auto_min_confirmations(cfg)
    max_route_age_seconds = _auto_max_route_age_seconds(cfg)
    use_multitimeframe_advisory = _auto_use_multitimeframe_advisory(cfg)
    advisory = {
        "suggested_regime": None,
        "confidence_score": None,
        "confidence_label": None,
        "insufficient_data": True,
        "insufficient_reason": "missing_shadow_state",
        "detection_source": "runtime_shadow",
        "detection_timestamp_epoch": None,
        "stability_score": None,
        "persistence_score": None,
        "data_quality_status": "UNKNOWN",
        "supported_key_windows": False,
    }
    if use_multitimeframe_advisory:
        advisory = _extract_regime_advisory(snapshot)
        if not advisory["suggested_regime"] and isinstance(shadow_state, dict):
            advisory = _extract_shadow_advisory(
                symbol=symbol,
                shadow_state=shadow_state,
                min_confirmations=min_confirmations,
            )
    elif isinstance(shadow_state, dict):
        advisory = _extract_shadow_advisory(
            symbol=symbol,
            shadow_state=shadow_state,
            min_confirmations=min_confirmations,
        )

    result["detected_regime"] = advisory["suggested_regime"]
    result["suggested_regime_v2"] = advisory["suggested_regime"]
    result["detected_regime_confidence"] = advisory["confidence_score"]
    result["detected_regime_confidence_label"] = advisory["confidence_label"]
    result["detected_regime_stability"] = advisory.get("stability_score")
    result["detected_regime_persistence"] = advisory.get("persistence_score")
    result["regime_data_quality_status"] = str(advisory.get("data_quality_status") or "UNKNOWN").upper()
    result["regime_key_windows_supported"] = _as_bool(advisory.get("supported_key_windows"), False)
    result["detection_source"] = str(advisory.get("detection_source") or "runtime_shadow")
    result["detection_timestamp_epoch"] = _as_float(advisory.get("detection_timestamp_epoch"))
    if result["regime_eval_ts"] is None:
        result["regime_eval_ts"] = result["detection_timestamp_epoch"]

    if not advisory["suggested_regime"]:
        if advisory.get("insufficient_reason") == "insufficient_shadow_confirmations":
            result["auto_fallback_reason"] = "insufficient_shadow_state"
        elif advisory.get("insufficient_reason") == "missing_shadow_state":
            result["auto_fallback_reason"] = "insufficient_shadow_state"
        else:
            result["auto_fallback_reason"] = "advisory_unavailable"
        result["fallback_reason"] = result["auto_fallback_reason"]
        return result

    if advisory["insufficient_data"]:
        if advisory.get("insufficient_reason") in {
            "insufficient_shadow_confirmations",
            "missing_shadow_state",
        }:
            result["auto_fallback_reason"] = "insufficient_shadow_state"
        else:
            result["auto_fallback_reason"] = "insufficient_advisory_data"
        result["fallback_reason"] = result["auto_fallback_reason"]
        return result

    confidence_score = _normalize_confidence_score(advisory["confidence_score"])
    if confidence_score is None or confidence_score < min_confidence_score:
        result["auto_fallback_reason"] = "low_confidence"
        result["fallback_reason"] = result["auto_fallback_reason"]
        return result

    stability_score = _normalize_confidence_score(advisory.get("stability_score"))
    if stability_score is None or stability_score < min_stability_score:
        result["auto_fallback_reason"] = "low_stability"
        result["fallback_reason"] = result["auto_fallback_reason"]
        return result

    persistence_score = _normalize_confidence_score(advisory.get("persistence_score"))
    if persistence_score is None or persistence_score < min_persistence_score:
        result["auto_fallback_reason"] = "low_persistence"
        result["fallback_reason"] = result["auto_fallback_reason"]
        return result

    if not _as_bool(advisory.get("supported_key_windows"), False):
        result["auto_fallback_reason"] = "unsupported_key_windows"
        result["fallback_reason"] = result["auto_fallback_reason"]
        return result

    data_quality_status = str(advisory.get("data_quality_status") or "UNKNOWN").upper()
    if data_quality_status in {"STALE", "INSUFFICIENT", "UNSUPPORTED_WINDOW"}:
        result["auto_fallback_reason"] = "data_quality_not_acceptable"
        result["fallback_reason"] = result["auto_fallback_reason"]
        return result

    detection_timestamp = _as_float(advisory.get("detection_timestamp_epoch"))
    route_eval_ts = _as_float(result.get("route_eval_ts")) or time.time()
    if detection_timestamp is not None and (route_eval_ts - detection_timestamp) > max_route_age_seconds:
        result["auto_fallback_reason"] = "route_timestamp_stale"
        result["fallback_reason"] = result["auto_fallback_reason"]
        return result

    mapped_strategy = SUGGESTED_REGIME_TO_STRATEGY.get(str(advisory["suggested_regime"]))
    if mapped_strategy is None:
        result["auto_fallback_reason"] = "mixed_or_unclear_regime"
        result["fallback_reason"] = result["auto_fallback_reason"]
        return result

    suggested_regime = str(advisory["suggested_regime"])
    if suggested_regime == SUGGESTED_REGIME_MIXED:
        result["auto_fallback_reason"] = "mixed_or_unclear_regime"
        result["fallback_reason"] = result["auto_fallback_reason"]
    elif suggested_regime == SUGGESTED_REGIME_HIGH_RISK_UNSTABLE:
        result["auto_fallback_reason"] = "high_risk_unstable"
        result["fallback_reason"] = result["auto_fallback_reason"]
    elif suggested_regime == SUGGESTED_REGIME_TREND_WEAKENING:
        result["auto_fallback_reason"] = "trend_weakening"
        result["fallback_reason"] = result["auto_fallback_reason"]

    result["effective_strategy"] = mapped_strategy
    result["effective_route"] = mapped_strategy
    return result
