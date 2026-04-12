from __future__ import annotations

import time
from dataclasses import dataclass
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
AUTO_DEFAULT_TREND_MIN_CONFIDENCE_SCORE = 74.0
AUTO_DEFAULT_TREND_MIN_STABILITY_SCORE = 68.0
AUTO_DEFAULT_TREND_MIN_PERSISTENCE_SCORE = 68.0
AUTO_DEFAULT_BREAKOUT_MIN_CONFIDENCE_SCORE = 82.0
AUTO_DEFAULT_BREAKOUT_MIN_STABILITY_SCORE = 76.0
AUTO_DEFAULT_BREAKOUT_MIN_PERSISTENCE_SCORE = 76.0
AUTO_DEFAULT_TREND_MAX_ROUTE_SHARE_PCT = 35.0
AUTO_DEFAULT_BREAKOUT_MAX_ROUTE_SHARE_PCT = 8.0

TUNING_PROFILE_CONSERVATIVE = "conservative"
TUNING_PROFILE_BALANCED = "balanced"
TUNING_PROFILE_AGGRESSIVE = "aggressive"
DEFAULT_TUNING_PROFILE = TUNING_PROFILE_CONSERVATIVE

@dataclass(frozen=True)
class StrategyThresholdProfile:
    min_confidence: float
    min_stability: float
    min_persistence: float
    max_route_share_pct: float | None = None


@dataclass(frozen=True)
class RouterThresholdProfile:
    max_route_age_seconds: float
    volatile_breakout_min: float
    volatile_breakout_min_confidence: float
    strategy_defaults: dict[str, StrategyThresholdProfile]

    def strategy(self, strategy: str) -> StrategyThresholdProfile:
        return self.strategy_defaults.get(strategy, self.strategy_defaults[STRATEGY_MEAN_REVERSION])


def _build_router_profile(
    *,
    mean_conf: float,
    mean_stability: float,
    mean_persistence: float,
    max_route_age_seconds: float,
    trend_conf: float,
    trend_stability: float,
    trend_persistence: float,
    trend_max_share: float,
    breakout_conf: float,
    breakout_stability: float,
    breakout_persistence: float,
    breakout_max_share: float,
    volatile_breakout_min: float,
    volatile_breakout_min_confidence: float,
) -> RouterThresholdProfile:
    mean_profile = StrategyThresholdProfile(
        min_confidence=float(mean_conf),
        min_stability=float(mean_stability),
        min_persistence=float(mean_persistence),
    )
    return RouterThresholdProfile(
        max_route_age_seconds=float(max_route_age_seconds),
        volatile_breakout_min=float(volatile_breakout_min),
        volatile_breakout_min_confidence=float(volatile_breakout_min_confidence),
        strategy_defaults={
            STRATEGY_MEAN_REVERSION: mean_profile,
            STRATEGY_OBSERVE_ONLY: mean_profile,
            STRATEGY_VOLATILITY_SCALPER: mean_profile,
            STRATEGY_TREND_PULLBACK: StrategyThresholdProfile(
                min_confidence=float(trend_conf),
                min_stability=float(trend_stability),
                min_persistence=float(trend_persistence),
                max_route_share_pct=float(trend_max_share),
            ),
            STRATEGY_BREAKOUT_MOMENTUM: StrategyThresholdProfile(
                min_confidence=float(breakout_conf),
                min_stability=float(breakout_stability),
                min_persistence=float(breakout_persistence),
                max_route_share_pct=float(breakout_max_share),
            ),
        },
    )


TUNING_PROFILE_DEFAULTS: dict[str, RouterThresholdProfile] = {
    TUNING_PROFILE_CONSERVATIVE: _build_router_profile(
        mean_conf=AUTO_DEFAULT_MIN_CONFIDENCE_SCORE,
        mean_stability=AUTO_DEFAULT_MIN_STABILITY_SCORE,
        mean_persistence=AUTO_DEFAULT_MIN_PERSISTENCE_SCORE,
        max_route_age_seconds=AUTO_DEFAULT_MAX_ROUTE_AGE_SECONDS,
        trend_conf=AUTO_DEFAULT_TREND_MIN_CONFIDENCE_SCORE,
        trend_stability=AUTO_DEFAULT_TREND_MIN_STABILITY_SCORE,
        trend_persistence=AUTO_DEFAULT_TREND_MIN_PERSISTENCE_SCORE,
        trend_max_share=AUTO_DEFAULT_TREND_MAX_ROUTE_SHARE_PCT,
        breakout_conf=AUTO_DEFAULT_BREAKOUT_MIN_CONFIDENCE_SCORE,
        breakout_stability=AUTO_DEFAULT_BREAKOUT_MIN_STABILITY_SCORE,
        breakout_persistence=AUTO_DEFAULT_BREAKOUT_MIN_PERSISTENCE_SCORE,
        breakout_max_share=AUTO_DEFAULT_BREAKOUT_MAX_ROUTE_SHARE_PCT,
        volatile_breakout_min=86.0,
        volatile_breakout_min_confidence=80.0,
    ),
    TUNING_PROFILE_BALANCED: _build_router_profile(
        mean_conf=66.0,
        mean_stability=56.0,
        mean_persistence=56.0,
        max_route_age_seconds=18 * 60,
        trend_conf=72.0,
        trend_stability=66.0,
        trend_persistence=66.0,
        trend_max_share=40.0,
        breakout_conf=80.0,
        breakout_stability=74.0,
        breakout_persistence=74.0,
        breakout_max_share=10.0,
        volatile_breakout_min=84.0,
        volatile_breakout_min_confidence=78.0,
    ),
    TUNING_PROFILE_AGGRESSIVE: _build_router_profile(
        mean_conf=64.0,
        mean_stability=54.0,
        mean_persistence=54.0,
        max_route_age_seconds=22 * 60,
        trend_conf=70.0,
        trend_stability=64.0,
        trend_persistence=64.0,
        trend_max_share=45.0,
        breakout_conf=78.0,
        breakout_stability=72.0,
        breakout_persistence=72.0,
        breakout_max_share=12.0,
        volatile_breakout_min=82.0,
        volatile_breakout_min_confidence=76.0,
    ),
}

SUGGESTED_REGIME_TREND_UP = "TREND_UP"
SUGGESTED_REGIME_TREND_DOWN = "TREND_DOWN"
SUGGESTED_REGIME_RANGE = "RANGE"
SUGGESTED_REGIME_BREAKOUT_UP = "BREAKOUT_UP"
SUGGESTED_REGIME_BREAKOUT_DOWN = "BREAKOUT_DOWN"
SUGGESTED_REGIME_MOMENTUM_UP = "MOMENTUM_UP"
SUGGESTED_REGIME_VOLATILE = "VOLATILE"
SUGGESTED_REGIME_LOW_VOL = "LOW_VOL"
SUGGESTED_REGIME_CHOPPY = "CHOPPY"
SUGGESTED_REGIME_UNKNOWN = "UNKNOWN"

SUGGESTED_REGIME_TO_STRATEGY = {
    SUGGESTED_REGIME_TREND_UP: STRATEGY_TREND_PULLBACK,
    SUGGESTED_REGIME_BREAKOUT_UP: STRATEGY_BREAKOUT_MOMENTUM,
    SUGGESTED_REGIME_MOMENTUM_UP: STRATEGY_BREAKOUT_MOMENTUM,
    SUGGESTED_REGIME_RANGE: STRATEGY_MEAN_REVERSION,
    SUGGESTED_REGIME_LOW_VOL: STRATEGY_MEAN_REVERSION,
    SUGGESTED_REGIME_TREND_DOWN: STRATEGY_OBSERVE_ONLY,
    SUGGESTED_REGIME_BREAKOUT_DOWN: STRATEGY_OBSERVE_ONLY,
    SUGGESTED_REGIME_VOLATILE: STRATEGY_OBSERVE_ONLY,
    SUGGESTED_REGIME_CHOPPY: STRATEGY_OBSERVE_ONLY,
    SUGGESTED_REGIME_UNKNOWN: STRATEGY_OBSERVE_ONLY,
}

RAW_REGIME_TO_SUGGESTED = {
    "trend_up": SUGGESTED_REGIME_TREND_UP,
    "trend_down": SUGGESTED_REGIME_TREND_DOWN,
    "range": SUGGESTED_REGIME_RANGE,
    "breakout_up": SUGGESTED_REGIME_BREAKOUT_UP,
    "breakout_down": SUGGESTED_REGIME_BREAKOUT_DOWN,
    "momentum_up": SUGGESTED_REGIME_MOMENTUM_UP,
    "volatile": SUGGESTED_REGIME_VOLATILE,
    "low_vol": SUGGESTED_REGIME_LOW_VOL,
    "choppy": SUGGESTED_REGIME_CHOPPY,
    "unknown": SUGGESTED_REGIME_UNKNOWN,
    # Backward-compatibility shims for historical raw regimes.
    "accumulation": SUGGESTED_REGIME_LOW_VOL,
    "spike": SUGGESTED_REGIME_BREAKOUT_UP,
    "dump": SUGGESTED_REGIME_BREAKOUT_DOWN,
    "chop": SUGGESTED_REGIME_CHOPPY,
}

LEGACY_SUGGESTED_TO_CURRENT = {
    "MEAN_REVERSION_FRIENDLY": SUGGESTED_REGIME_RANGE,
    "TREND_CONTINUATION": SUGGESTED_REGIME_TREND_UP,
    "BREAKOUT_EXPANSION": SUGGESTED_REGIME_BREAKOUT_UP,
    "TREND_WEAKENING": SUGGESTED_REGIME_TREND_DOWN,
    "HIGH_RISK_UNSTABLE": SUGGESTED_REGIME_CHOPPY,
    "ACCUMULATION": SUGGESTED_REGIME_LOW_VOL,
    "DISTRIBUTION": SUGGESTED_REGIME_TREND_DOWN,
    "LIQUIDITY_SWEEP_REVERSAL": SUGGESTED_REGIME_BREAKOUT_UP,
    "VOLATILITY_COMPRESSION": SUGGESTED_REGIME_LOW_VOL,
    "SLOW_BLEED": SUGGESTED_REGIME_TREND_DOWN,
    "CAPITULATION_PANIC": SUGGESTED_REGIME_BREAKOUT_DOWN,
    "LOW_PARTICIPATION_DEAD_MARKET": SUGGESTED_REGIME_LOW_VOL,
    "MIXED_OR_UNCLEAR": SUGGESTED_REGIME_UNKNOWN,
}

HUMAN_LABEL_TO_SUGGESTED = {
    "TREND UP": SUGGESTED_REGIME_TREND_UP,
    "TREND DOWN": SUGGESTED_REGIME_TREND_DOWN,
    "RANGE": SUGGESTED_REGIME_RANGE,
    "BREAKOUT UP": SUGGESTED_REGIME_BREAKOUT_UP,
    "BREAKOUT DOWN": SUGGESTED_REGIME_BREAKOUT_DOWN,
    "MOMENTUM UP": SUGGESTED_REGIME_MOMENTUM_UP,
    "VOLATILE / UNSTABLE": SUGGESTED_REGIME_VOLATILE,
    "LOW VOLATILITY": SUGGESTED_REGIME_LOW_VOL,
    "CHOPPY / NO-TRADE": SUGGESTED_REGIME_CHOPPY,
    "UNKNOWN": SUGGESTED_REGIME_UNKNOWN,
    # Backward-compatibility labels.
    "MEAN-REVERSION-FRIENDLY RANGE": SUGGESTED_REGIME_RANGE,
    "TREND CONTINUATION / PULLBACK": SUGGESTED_REGIME_TREND_UP,
    "BREAKOUT EXPANSION": SUGGESTED_REGIME_BREAKOUT_UP,
    "TREND WEAKENING": SUGGESTED_REGIME_TREND_DOWN,
    "HIGH-RISK UNSTABLE / WHIPSAW": SUGGESTED_REGIME_CHOPPY,
    "ACCUMULATION": SUGGESTED_REGIME_LOW_VOL,
    "DISTRIBUTION": SUGGESTED_REGIME_TREND_DOWN,
    "LIQUIDITY SWEEP REVERSAL": SUGGESTED_REGIME_BREAKOUT_UP,
    "VOLATILITY COMPRESSION / SQUEEZE": SUGGESTED_REGIME_LOW_VOL,
    "SLOW BLEED / DOWNTREND DRIFT": SUGGESTED_REGIME_TREND_DOWN,
    "CAPITULATION / PANIC FLUSH": SUGGESTED_REGIME_BREAKOUT_DOWN,
    "LOW-PARTICIPATION DEAD MARKET": SUGGESTED_REGIME_LOW_VOL,
    "MIXED / UNCLEAR": SUGGESTED_REGIME_UNKNOWN,
}


@dataclass(frozen=True)
class AutoRouterThresholds:
    min_confirmations: int
    max_route_age_seconds: float
    use_multitimeframe_advisory: bool
    use_route_quality_gates: bool
    require_core_candle_readiness: bool
    min_confidence_by_strategy: dict[str, float]
    min_stability_by_strategy: dict[str, float]
    min_persistence_by_strategy: dict[str, float]
    max_route_share_pct_by_strategy: dict[str, float | None]
    volatile_breakout_min: float
    volatile_breakout_min_confidence: float

    def min_confidence(self, strategy: str) -> float:
        return float(self.min_confidence_by_strategy.get(strategy, self.min_confidence_by_strategy[STRATEGY_MEAN_REVERSION]))

    def min_stability(self, strategy: str) -> float:
        return float(self.min_stability_by_strategy.get(strategy, self.min_stability_by_strategy[STRATEGY_MEAN_REVERSION]))

    def min_persistence(self, strategy: str) -> float:
        return float(self.min_persistence_by_strategy.get(strategy, self.min_persistence_by_strategy[STRATEGY_MEAN_REVERSION]))

    def max_route_share_pct(self, strategy: str) -> float | None:
        return self.max_route_share_pct_by_strategy.get(strategy)


def _normalize_suggested_regime(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    upper = raw.upper()
    if upper in SUGGESTED_REGIME_TO_STRATEGY:
        return upper
    legacy_mapped = LEGACY_SUGGESTED_TO_CURRENT.get(upper)
    if legacy_mapped:
        return legacy_mapped
    mapped = HUMAN_LABEL_TO_SUGGESTED.get(upper)
    if mapped:
        return mapped
    raw_mapped = RAW_REGIME_TO_SUGGESTED.get(raw.lower())
    if raw_mapped:
        return raw_mapped
    return None


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


def _tuning_profile(cfg: dict[str, Any]) -> str:
    strategy_defaults = cfg.get("strategy_defaults", {})
    if not isinstance(strategy_defaults, dict):
        return DEFAULT_TUNING_PROFILE
    raw = strategy_defaults.get("tuning_profile")
    profile = str(raw or "").strip().lower()
    if profile in TUNING_PROFILE_DEFAULTS:
        return profile
    return DEFAULT_TUNING_PROFILE


def _profile_defaults(cfg: dict[str, Any]) -> RouterThresholdProfile:
    profile = _tuning_profile(cfg)
    return TUNING_PROFILE_DEFAULTS.get(profile, TUNING_PROFILE_DEFAULTS[DEFAULT_TUNING_PROFILE])


_STRATEGY_THRESHOLD_OVERRIDE_KEYS: dict[str, dict[str, str]] = {
    "min_confidence": {
        STRATEGY_MEAN_REVERSION: "auto_min_confidence",
        STRATEGY_TREND_PULLBACK: "auto_trend_min_confidence",
        STRATEGY_BREAKOUT_MOMENTUM: "auto_breakout_min_confidence",
    },
    "min_stability": {
        STRATEGY_MEAN_REVERSION: "auto_min_stability",
        STRATEGY_TREND_PULLBACK: "auto_trend_min_stability",
        STRATEGY_BREAKOUT_MOMENTUM: "auto_breakout_min_stability",
    },
    "min_persistence": {
        STRATEGY_MEAN_REVERSION: "auto_min_persistence",
        STRATEGY_TREND_PULLBACK: "auto_trend_min_persistence",
        STRATEGY_BREAKOUT_MOMENTUM: "auto_breakout_min_persistence",
    },
    "max_route_share_pct": {
        STRATEGY_TREND_PULLBACK: "auto_trend_max_route_share_pct",
        STRATEGY_BREAKOUT_MOMENTUM: "auto_breakout_max_route_share_pct",
    },
}


def _strategy_threshold_default(cfg: dict[str, Any], strategy: str) -> StrategyThresholdProfile:
    return _profile_defaults(cfg).strategy(strategy)


def _strategy_threshold(cfg: dict[str, Any], strategy: str, metric: str) -> float | None:
    defaults = _strategy_threshold_default(cfg, strategy)
    key_map = _STRATEGY_THRESHOLD_OVERRIDE_KEYS.get(metric, {})
    override_key = key_map.get(strategy)
    if override_key is None:
        if metric == "max_route_share_pct":
            return defaults.max_route_share_pct
        return float(getattr(defaults, metric))

    router = _router_cfg(cfg)
    raw_value = router.get(override_key)
    if metric == "max_route_share_pct":
        configured = _as_float(raw_value)
        if configured is None:
            return defaults.max_route_share_pct
        return max(0.0, min(configured, 100.0))

    configured = _normalize_confidence_score(raw_value)
    if configured is None:
        return float(getattr(defaults, metric))
    return configured


def _auto_min_confidence_score(cfg: dict[str, Any]) -> float:
    return float(_strategy_threshold(cfg, STRATEGY_MEAN_REVERSION, "min_confidence") or AUTO_DEFAULT_MIN_CONFIDENCE_SCORE)


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
    return float(_strategy_threshold(cfg, STRATEGY_MEAN_REVERSION, "min_stability") or AUTO_DEFAULT_MIN_STABILITY_SCORE)


def _auto_min_persistence_score(cfg: dict[str, Any]) -> float:
    return float(_strategy_threshold(cfg, STRATEGY_MEAN_REVERSION, "min_persistence") or AUTO_DEFAULT_MIN_PERSISTENCE_SCORE)


def _auto_use_route_quality_gates(cfg: dict[str, Any]) -> bool:
    router = _router_cfg(cfg)
    return _as_bool(router.get("auto_use_route_quality_gates"), True)


def _auto_strategy_min_confidence_score(cfg: dict[str, Any], strategy: str) -> float:
    value = _strategy_threshold(cfg, strategy, "min_confidence")
    if value is None:
        return _auto_min_confidence_score(cfg)
    return float(value)


def _auto_strategy_min_stability_score(cfg: dict[str, Any], strategy: str) -> float:
    value = _strategy_threshold(cfg, strategy, "min_stability")
    if value is None:
        return _auto_min_stability_score(cfg)
    return float(value)


def _auto_strategy_min_persistence_score(cfg: dict[str, Any], strategy: str) -> float:
    value = _strategy_threshold(cfg, strategy, "min_persistence")
    if value is None:
        return _auto_min_persistence_score(cfg)
    return float(value)


def _auto_strategy_max_route_share_pct(cfg: dict[str, Any], strategy: str) -> float | None:
    return _strategy_threshold(cfg, strategy, "max_route_share_pct")


def _route_quality_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = snapshot.get("route_quality")
    if not isinstance(payload, dict):
        return {}
    return payload


def _is_route_promoted(snapshot: dict[str, Any], strategy: str) -> tuple[bool, str]:
    payload = _route_quality_payload(snapshot)
    promotion = payload.get("promotion")
    if not isinstance(promotion, dict):
        return False, "route_quality_unavailable"
    promoted_routes = promotion.get("promoted_routes")
    reasons = promotion.get("promotion_reasons")
    if not isinstance(promoted_routes, dict):
        return False, "route_quality_unavailable"
    promoted = _as_bool(promoted_routes.get(strategy), False)
    reason = "not_promoted"
    if isinstance(reasons, dict):
        reason = str(reasons.get(strategy) or reason)
    return promoted, reason


def _route_share_pct(snapshot: dict[str, Any], strategy: str) -> float | None:
    payload = _route_quality_payload(snapshot)
    current = payload.get("current")
    if not isinstance(current, dict):
        return None
    counts = current.get("effective_route_counts")
    if not isinstance(counts, dict):
        return None
    total = 0.0
    target = 0.0
    for route, raw in counts.items():
        value = _as_float(raw)
        if value is None or value < 0:
            continue
        total += value
        if str(route).strip().lower() == strategy:
            target += value
    if total <= 0:
        return None
    return (target / total) * 100.0


def _auto_max_route_age_seconds(cfg: dict[str, Any]) -> float:
    router = _router_cfg(cfg)
    age = _as_float(router.get("auto_max_route_age_seconds"))
    if age is None or age <= 0:
        return float(_profile_defaults(cfg).max_route_age_seconds)
    return max(age, 60.0)


def _auto_require_core_candle_readiness(cfg: dict[str, Any]) -> bool:
    router = _router_cfg(cfg)
    return _as_bool(router.get("auto_require_core_candle_readiness"), True)


def _build_auto_router_thresholds(cfg: dict[str, Any]) -> AutoRouterThresholds:
    profile_defaults = _profile_defaults(cfg)
    mean_conf = _auto_min_confidence_score(cfg)
    mean_stability = _auto_min_stability_score(cfg)
    mean_persistence = _auto_min_persistence_score(cfg)
    trend_conf = _auto_strategy_min_confidence_score(cfg, STRATEGY_TREND_PULLBACK)
    trend_stability = _auto_strategy_min_stability_score(cfg, STRATEGY_TREND_PULLBACK)
    trend_persistence = _auto_strategy_min_persistence_score(cfg, STRATEGY_TREND_PULLBACK)
    breakout_conf = _auto_strategy_min_confidence_score(cfg, STRATEGY_BREAKOUT_MOMENTUM)
    breakout_stability = _auto_strategy_min_stability_score(cfg, STRATEGY_BREAKOUT_MOMENTUM)
    breakout_persistence = _auto_strategy_min_persistence_score(cfg, STRATEGY_BREAKOUT_MOMENTUM)
    volatile_breakout_min = _normalize_confidence_score(_router_cfg(cfg).get("auto_volatile_breakout_min"))
    if volatile_breakout_min is None:
        volatile_breakout_min = float(profile_defaults.volatile_breakout_min)
    volatile_breakout_min_conf = _normalize_confidence_score(_router_cfg(cfg).get("auto_volatile_breakout_min_confidence"))
    if volatile_breakout_min_conf is None:
        volatile_breakout_min_conf = float(profile_defaults.volatile_breakout_min_confidence)

    return AutoRouterThresholds(
        min_confirmations=_auto_min_confirmations(cfg),
        max_route_age_seconds=_auto_max_route_age_seconds(cfg),
        use_multitimeframe_advisory=_auto_use_multitimeframe_advisory(cfg),
        use_route_quality_gates=_auto_use_route_quality_gates(cfg),
        require_core_candle_readiness=_auto_require_core_candle_readiness(cfg),
        min_confidence_by_strategy={
            STRATEGY_MEAN_REVERSION: mean_conf,
            STRATEGY_TREND_PULLBACK: trend_conf,
            STRATEGY_BREAKOUT_MOMENTUM: breakout_conf,
            STRATEGY_OBSERVE_ONLY: mean_conf,
            STRATEGY_VOLATILITY_SCALPER: mean_conf,
        },
        min_stability_by_strategy={
            STRATEGY_MEAN_REVERSION: mean_stability,
            STRATEGY_TREND_PULLBACK: trend_stability,
            STRATEGY_BREAKOUT_MOMENTUM: breakout_stability,
            STRATEGY_OBSERVE_ONLY: mean_stability,
            STRATEGY_VOLATILITY_SCALPER: mean_stability,
        },
        min_persistence_by_strategy={
            STRATEGY_MEAN_REVERSION: mean_persistence,
            STRATEGY_TREND_PULLBACK: trend_persistence,
            STRATEGY_BREAKOUT_MOMENTUM: breakout_persistence,
            STRATEGY_OBSERVE_ONLY: mean_persistence,
            STRATEGY_VOLATILITY_SCALPER: mean_persistence,
        },
        max_route_share_pct_by_strategy={
            STRATEGY_TREND_PULLBACK: _auto_strategy_max_route_share_pct(cfg, STRATEGY_TREND_PULLBACK),
            STRATEGY_BREAKOUT_MOMENTUM: _auto_strategy_max_route_share_pct(cfg, STRATEGY_BREAKOUT_MOMENTUM),
        },
        volatile_breakout_min=float(volatile_breakout_min),
        volatile_breakout_min_confidence=float(volatile_breakout_min_conf),
    )


def _core_candle_readiness(snapshot: dict[str, Any]) -> tuple[bool, str | None]:
    payload = snapshot.get("core_candle_readiness")
    if not isinstance(payload, dict):
        # Backward compatibility: enforce readiness only when payload is supplied.
        return True, None
    ready = _as_bool(payload.get("ready"), False)
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = "core_candle_readiness_not_ready"
    return ready, reason.strip().lower()


def _volatile_breakout_override(
    snapshot: dict[str, Any],
    cfg: dict[str, Any],
    confidence_score: float | None,
    *,
    thresholds: AutoRouterThresholds | None = None,
) -> bool:
    advisory = snapshot.get("regime_advisory")
    if not isinstance(advisory, dict):
        return False
    breakout_score = _normalize_confidence_score(
        advisory.get("breakoutScore", advisory.get("breakout_score"))
    )
    if breakout_score is None:
        return False
    threshold_set = thresholds if isinstance(thresholds, AutoRouterThresholds) else _build_auto_router_thresholds(cfg)
    breakout_min = float(threshold_set.volatile_breakout_min)
    confidence_min = float(threshold_set.volatile_breakout_min_confidence)
    confidence_probe = confidence_score if confidence_score is not None else 0.0
    return breakout_score >= breakout_min and confidence_probe >= confidence_min


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
        confidence_score = _normalize_confidence_score(snapshot.get("detected_regime_confidence_score"))
    if confidence_score is None:
        confidence_score = _normalize_confidence_score(snapshot.get("detectedRegimeConfidence"))
    if confidence_score is None:
        confidence_score = _normalize_confidence_score(snapshot.get("detectedRegimeConfidenceScore"))

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
    if stability_score is None:
        stability_score = _normalize_confidence_score(snapshot.get("detected_regime_stability"))
    if stability_score is None:
        stability_score = _normalize_confidence_score(snapshot.get("detected_regime_stability_score"))
    persistence_score = _normalize_confidence_score(advisory.get("persistenceScore"))
    if persistence_score is None:
        persistence_score = _normalize_confidence_score(advisory.get("persistence_score"))
    if persistence_score is None:
        persistence_score = _normalize_confidence_score(snapshot.get("detected_regime_persistence"))
    if persistence_score is None:
        persistence_score = _normalize_confidence_score(snapshot.get("detected_regime_persistence_score"))
    stability_inferred = False
    persistence_inferred = False
    if stability_score is None:
        stability_score = confidence_score
        stability_inferred = stability_score is not None
    if persistence_score is None:
        persistence_score = confidence_score
        persistence_inferred = persistence_score is not None

    data_quality = advisory.get("dataQuality")
    if not isinstance(data_quality, dict):
        data_quality = advisory.get("data_quality")
    if not isinstance(data_quality, dict):
        data_quality = {}

    data_quality_status = data_quality.get("status")
    if not isinstance(data_quality_status, str):
        data_quality_status = "UNKNOWN"
    data_quality_status = data_quality_status.strip().upper() or "UNKNOWN"
    supported_key_windows = _as_bool(data_quality.get("supportedKeyWindows"), False)
    if "supported_key_windows" in data_quality:
        supported_key_windows = _as_bool(data_quality.get("supported_key_windows"), supported_key_windows)
    supported_window_count = _as_float(data_quality.get("supportedWindowCount"))
    if supported_window_count is None:
        supported_window_count = _as_float(data_quality.get("supported_window_count"))

    insufficient_reason_code = advisory.get("insufficientReasonCode")
    if not isinstance(insufficient_reason_code, str):
        insufficient_reason_code = advisory.get("insufficient_reason_code")
    if isinstance(insufficient_reason_code, str):
        insufficient_reason_code = insufficient_reason_code.strip().lower() or None
    else:
        insufficient_reason_code = None

    insufficient_reason_message = advisory.get("insufficientReasonMessage")
    if not isinstance(insufficient_reason_message, str):
        insufficient_reason_message = advisory.get("insufficient_reason_message")
    if isinstance(insufficient_reason_message, str):
        insufficient_reason_message = insufficient_reason_message.strip() or None
    else:
        insufficient_reason_message = None

    timeframe_summary = advisory.get("timeframeSummary")
    if not isinstance(timeframe_summary, list):
        timeframe_summary = advisory.get("timeframe_summary")
    if not isinstance(timeframe_summary, list):
        timeframe_summary = None

    normalized_suggested = _normalize_suggested_regime(suggested) or ""

    return {
        "suggested_regime": normalized_suggested or None,
        "confidence_score": confidence_score,
        "confidence_label": confidence_label,
        "insufficient_data": insufficient_data,
        "insufficient_reason": "snapshot_advisory_insufficient" if insufficient_data else None,
        "insufficient_reason_code": insufficient_reason_code,
        "insufficient_reason_message": insufficient_reason_message,
        "detection_source": detection_source.strip().lower(),
        "detection_timestamp_epoch": detection_timestamp_epoch,
        "stability_score": stability_score,
        "persistence_score": persistence_score,
        "stability_inferred": stability_inferred,
        "persistence_inferred": persistence_inferred,
        "data_quality_status": data_quality_status,
        "supported_key_windows": supported_key_windows,
        "supported_window_count": supported_window_count,
        "timeframe_summary": timeframe_summary,
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
            "stability_inferred": False,
            "persistence_inferred": False,
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
            "stability_inferred": False,
            "persistence_inferred": False,
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
            "stability_inferred": True,
            "persistence_inferred": True,
            "data_quality_status": "PARTIAL",
            "supported_key_windows": True,
        }

    stable = str(
        row.get("stable_regime")
        or row.get("candidate_regime")
        or "unknown"
    ).strip().lower()
    suggested = RAW_REGIME_TO_SUGGESTED.get(stable, SUGGESTED_REGIME_UNKNOWN)
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
        "stability_inferred": True,
        "persistence_inferred": True,
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


def _is_manual_scalper_toggle_enabled(cfg: dict[str, Any], symbol: str) -> bool:
    symbol_key = normalize_symbol(symbol)
    if not symbol_key:
        return False

    symbol_strategies = cfg.get("symbol_strategies", {})
    if isinstance(symbol_strategies, dict):
        for raw_symbol, raw_strategy in symbol_strategies.items():
            if normalize_symbol(raw_symbol) != symbol_key:
                continue
            return _normalize_default_strategy(raw_strategy) == STRATEGY_VOLATILITY_SCALPER
    return False


def resolve_entry_route(
    *,
    cfg: dict[str, Any],
    symbol: str,
    snapshot: dict[str, Any],
    default_strategy: str,
    shadow_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    configured_regime = _configured_regime(cfg, symbol)
    manual_scalper_toggle = _is_manual_scalper_toggle_enabled(cfg, symbol)
    thresholds = _build_auto_router_thresholds(cfg)
    max_route_age_seconds = thresholds.max_route_age_seconds
    route_eval_ts = _as_float(snapshot.get("router_eval_ts")) or time.time()
    min_confidence_score: float | None = None
    min_stability_score: float | None = None
    min_persistence_score: float | None = None
    promoted_state: bool | None = None
    promotion_reason: str | None = None
    route_share_pct: float | None = None
    route_share_cap_pct: float | None = None

    result = {
        "configured_regime": configured_regime,
        "detected_regime": None,
        "suggested_regime_v2": None,
        "detected_regime_confidence": None,
        "detected_regime_confidence_score": None,
        "detected_regime_confidence_label": None,
        "detected_regime_stability": None,
        "detected_regime_stability_score": None,
        "detected_regime_persistence": None,
        "detected_regime_persistence_score": None,
        "detected_regime_stability_inferred": False,
        "detected_regime_persistence_inferred": False,
        "regime_data_quality_status": "UNKNOWN",
        "regime_key_windows_supported": False,
        "regime_supported_window_count": None,
        "regime_insufficient_reason_code": None,
        "regime_insufficient_reason_message": None,
        "regime_timeframe_summary": None,
        "detection_source": "configured_manual",
        "detection_timestamp_epoch": None,
        # AUTO and unclear cases must degrade to frozen mean reversion by default.
        "effective_strategy": STRATEGY_MEAN_REVERSION,
        "effective_route": STRATEGY_MEAN_REVERSION,
        "route_eval_ts": route_eval_ts,
        "regime_eval_ts": _as_float(snapshot.get("regime_eval_ts")),
        "auto_fallback_reason": None,
        "fallback_reason": None,
        "ready_for_non_mr_route": False,
        "non_mr_ready_reason": "mean_reversion_default",
        "route_readiness_state": "FALLBACK",
        "failed_gates": [],
        "route_timestamp_age_seconds": None,
        "route_timestamp_fresh": False,
        "shadow_continuity_state": "missing",
        "shadow_age_seconds": None,
        "fallback_gate": None,
        "decision_diagnostics": {},
    }

    symbol_key = normalize_symbol(symbol)
    shadow_row = None
    if isinstance(shadow_state, dict) and symbol_key:
        row = shadow_state.get(symbol_key)
        shadow_row = row if isinstance(row, dict) else None
    shadow_last_update = _as_float(shadow_row.get("last_update_ts")) if isinstance(shadow_row, dict) else None
    if shadow_last_update is not None and shadow_last_update > 0:
        shadow_age = max(0.0, route_eval_ts - shadow_last_update)
        result["shadow_age_seconds"] = shadow_age
        result["shadow_continuity_state"] = "healthy" if shadow_age <= max_route_age_seconds else "stale"
    else:
        result["shadow_continuity_state"] = "missing"
        result["shadow_age_seconds"] = None

    def _sync_decision_diagnostics():
        result["decision_diagnostics"] = {
            "thresholds": {
                "min_confidence_score": min_confidence_score,
                "min_stability_score": min_stability_score,
                "min_persistence_score": min_persistence_score,
                "max_route_age_seconds": max_route_age_seconds,
                "min_shadow_confirmations": min_confirmations if "min_confirmations" in locals() else None,
            },
            "observed": {
                "detected_regime": result.get("detected_regime"),
                "confidence_score": result.get("detected_regime_confidence"),
                "stability_score": result.get("detected_regime_stability"),
                "persistence_score": result.get("detected_regime_persistence"),
                "route_timestamp_age_seconds": result.get("route_timestamp_age_seconds"),
                "route_timestamp_fresh": result.get("route_timestamp_fresh"),
                "shadow_continuity_state": result.get("shadow_continuity_state"),
                "shadow_age_seconds": result.get("shadow_age_seconds"),
                "regime_data_quality_status": result.get("regime_data_quality_status"),
                "regime_key_windows_supported": result.get("regime_key_windows_supported"),
                "regime_supported_window_count": result.get("regime_supported_window_count"),
                "regime_insufficient_reason_code": result.get("regime_insufficient_reason_code"),
                "regime_timeframe_summary": result.get("regime_timeframe_summary"),
                "route_quality_promoted": promoted_state,
                "route_quality_promotion_reason": promotion_reason,
                "route_share_pct": route_share_pct,
                "route_share_cap_pct": route_share_cap_pct,
            },
            "outcome": {
                "effective_strategy": result.get("effective_strategy"),
                "effective_route": result.get("effective_route"),
                "route_readiness_state": result.get("route_readiness_state"),
                "ready_for_non_mr_route": result.get("ready_for_non_mr_route"),
                "non_mr_ready_reason": result.get("non_mr_ready_reason"),
                "fallback_reason": result.get("fallback_reason"),
                "fallback_gate": result.get("fallback_gate"),
                "failed_gates": list(result.get("failed_gates") or []),
            },
        }

    def _mark_not_ready(reason: str, gate: str | None = None):
        result["ready_for_non_mr_route"] = False
        result["non_mr_ready_reason"] = str(reason or "not_ready")
        result["route_readiness_state"] = "FALLBACK"
        if isinstance(gate, str) and gate:
            gates = result.get("failed_gates")
            if not isinstance(gates, list):
                gates = []
            if gate not in gates:
                gates.append(gate)
            result["failed_gates"] = gates
            result["fallback_gate"] = gate
        _sync_decision_diagnostics()

    def _mark_ready(reason: str):
        result["ready_for_non_mr_route"] = True
        result["non_mr_ready_reason"] = str(reason or "ready")
        result["route_readiness_state"] = "READY"
        result["failed_gates"] = []
        result["fallback_gate"] = None
        _sync_decision_diagnostics()

    # Manual scalper mode must not clash with AUTO/manual regime routing.
    # When explicitly selected per-symbol, force scalper route.
    if manual_scalper_toggle:
        result["detection_source"] = "configured_manual_scalper"
        result["effective_strategy"] = STRATEGY_VOLATILITY_SCALPER
        result["effective_route"] = STRATEGY_VOLATILITY_SCALPER
        result["auto_fallback_reason"] = "manual_scalper_override"
        result["fallback_reason"] = "manual_scalper_override"
        result["route_timestamp_age_seconds"] = 0.0
        result["route_timestamp_fresh"] = True
        _mark_ready("manual_scalper_override")
        return result

    if configured_regime == TOKEN_REGIME_OBSERVE_ONLY:
        result["effective_strategy"] = STRATEGY_OBSERVE_ONLY
        result["effective_route"] = STRATEGY_OBSERVE_ONLY
        result["route_timestamp_age_seconds"] = 0.0
        result["route_timestamp_fresh"] = True
        _mark_not_ready("observe_only", gate="observe_only")
        return result

    if configured_regime == TOKEN_REGIME_TREND_PULLBACK:
        result["effective_strategy"] = STRATEGY_TREND_PULLBACK
        result["effective_route"] = STRATEGY_TREND_PULLBACK
        result["route_timestamp_age_seconds"] = 0.0
        result["route_timestamp_fresh"] = True
        _mark_ready("manual_forced_route")
        return result

    if configured_regime == TOKEN_REGIME_BREAKOUT_MOMENTUM:
        result["effective_strategy"] = STRATEGY_BREAKOUT_MOMENTUM
        result["effective_route"] = STRATEGY_BREAKOUT_MOMENTUM
        result["route_timestamp_age_seconds"] = 0.0
        result["route_timestamp_fresh"] = True
        _mark_ready("manual_forced_route")
        return result

    # Preserve default behavior for explicit manual mean-reversion mode.
    if configured_regime == TOKEN_REGIME_MEAN_REVERSION:
        result["effective_strategy"] = STRATEGY_MEAN_REVERSION
        result["effective_route"] = STRATEGY_MEAN_REVERSION
        result["route_timestamp_age_seconds"] = 0.0
        result["route_timestamp_fresh"] = True
        _mark_not_ready("manual_mean_reversion", gate="manual_mean_reversion")
        return result

    min_confidence_score = thresholds.min_confidence(STRATEGY_MEAN_REVERSION)
    min_stability_score = thresholds.min_stability(STRATEGY_MEAN_REVERSION)
    min_persistence_score = thresholds.min_persistence(STRATEGY_MEAN_REVERSION)
    min_confirmations = thresholds.min_confirmations
    use_multitimeframe_advisory = thresholds.use_multitimeframe_advisory
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
    result["detected_regime_confidence_score"] = advisory["confidence_score"]
    result["detected_regime_confidence_label"] = advisory["confidence_label"]
    result["detected_regime_stability"] = advisory.get("stability_score")
    result["detected_regime_stability_score"] = advisory.get("stability_score")
    result["detected_regime_persistence"] = advisory.get("persistence_score")
    result["detected_regime_persistence_score"] = advisory.get("persistence_score")
    result["detected_regime_stability_inferred"] = _as_bool(advisory.get("stability_inferred"), False)
    result["detected_regime_persistence_inferred"] = _as_bool(advisory.get("persistence_inferred"), False)
    result["regime_data_quality_status"] = str(advisory.get("data_quality_status") or "UNKNOWN").upper()
    result["regime_key_windows_supported"] = _as_bool(advisory.get("supported_key_windows"), False)
    result["regime_supported_window_count"] = _as_float(advisory.get("supported_window_count"))
    result["regime_insufficient_reason_code"] = advisory.get("insufficient_reason_code")
    result["regime_insufficient_reason_message"] = advisory.get("insufficient_reason_message")
    timeframe_summary = advisory.get("timeframe_summary")
    result["regime_timeframe_summary"] = timeframe_summary if isinstance(timeframe_summary, list) else None
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
        gate = "insufficient_shadow_state" if result["auto_fallback_reason"] == "insufficient_shadow_state" else "advisory_unavailable"
        _mark_not_ready(result["fallback_reason"], gate=gate)
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
        _mark_not_ready(result["fallback_reason"], gate=result["auto_fallback_reason"])
        return result

    if not _as_bool(advisory.get("supported_key_windows"), False):
        result["auto_fallback_reason"] = "unsupported_key_windows"
        result["fallback_reason"] = result["auto_fallback_reason"]
        _mark_not_ready(result["fallback_reason"], gate="unsupported_key_windows")
        return result

    data_quality_status = str(advisory.get("data_quality_status") or "UNKNOWN").upper()
    if data_quality_status in {"STALE", "INSUFFICIENT", "UNSUPPORTED_WINDOW"}:
        result["auto_fallback_reason"] = "data_quality_not_acceptable"
        result["fallback_reason"] = result["auto_fallback_reason"]
        _mark_not_ready(result["fallback_reason"], gate="data_quality_not_acceptable")
        return result

    if thresholds.require_core_candle_readiness:
        readiness_ok, readiness_reason = _core_candle_readiness(snapshot)
        if not readiness_ok:
            result["auto_fallback_reason"] = "core_timeframe_not_ready"
            result["fallback_reason"] = f"core_timeframe_not_ready:{readiness_reason}"
            _mark_not_ready(result["fallback_reason"], gate="core_timeframe_not_ready")
            return result

    detection_timestamp = _as_float(advisory.get("detection_timestamp_epoch"))
    route_eval_ts = _as_float(result.get("route_eval_ts")) or route_eval_ts
    if detection_timestamp is not None:
        route_age = max(0.0, route_eval_ts - detection_timestamp)
        result["route_timestamp_age_seconds"] = route_age
        result["route_timestamp_fresh"] = route_age <= max_route_age_seconds
    else:
        result["route_timestamp_age_seconds"] = None
        result["route_timestamp_fresh"] = False
    if detection_timestamp is not None and (route_eval_ts - detection_timestamp) > max_route_age_seconds:
        result["auto_fallback_reason"] = "route_timestamp_stale"
        result["fallback_reason"] = result["auto_fallback_reason"]
        _mark_not_ready(result["fallback_reason"], gate="route_timestamp_stale")
        return result

    suggested_regime = str(advisory["suggested_regime"] or SUGGESTED_REGIME_UNKNOWN)
    mapped_strategy = SUGGESTED_REGIME_TO_STRATEGY.get(suggested_regime)
    if mapped_strategy is None:
        result["auto_fallback_reason"] = "mixed_or_unclear_regime"
        result["fallback_reason"] = result["auto_fallback_reason"]
        _mark_not_ready(result["fallback_reason"], gate="mixed_or_unclear_regime")
        return result

    confidence_score = _normalize_confidence_score(advisory["confidence_score"])
    if (
        suggested_regime == SUGGESTED_REGIME_VOLATILE
        and mapped_strategy == STRATEGY_OBSERVE_ONLY
        and _volatile_breakout_override(snapshot, cfg, confidence_score, thresholds=thresholds)
    ):
        mapped_strategy = STRATEGY_BREAKOUT_MOMENTUM

    min_confidence_score = thresholds.min_confidence(mapped_strategy)
    min_stability_score = thresholds.min_stability(mapped_strategy)
    min_persistence_score = thresholds.min_persistence(mapped_strategy)

    if confidence_score is None or confidence_score < min_confidence_score:
        result["auto_fallback_reason"] = "low_confidence"
        result["fallback_reason"] = result["auto_fallback_reason"]
        _mark_not_ready(result["fallback_reason"], gate="low_confidence")
        return result

    stability_score = _normalize_confidence_score(advisory.get("stability_score"))
    if stability_score is None or stability_score < min_stability_score:
        result["auto_fallback_reason"] = "low_stability"
        result["fallback_reason"] = result["auto_fallback_reason"]
        _mark_not_ready(result["fallback_reason"], gate="low_stability")
        return result

    persistence_score = _normalize_confidence_score(advisory.get("persistence_score"))
    if persistence_score is None or persistence_score < min_persistence_score:
        result["auto_fallback_reason"] = "low_persistence"
        result["fallback_reason"] = result["auto_fallback_reason"]
        _mark_not_ready(result["fallback_reason"], gate="low_persistence")
        return result

    if thresholds.use_route_quality_gates and mapped_strategy in {STRATEGY_TREND_PULLBACK, STRATEGY_BREAKOUT_MOMENTUM}:
        promoted, promotion_reason = _is_route_promoted(snapshot, mapped_strategy)
        promoted_state = promoted
        if not promoted:
            result["auto_fallback_reason"] = "route_not_promoted"
            result["fallback_reason"] = f"route_not_promoted:{promotion_reason}"
            _mark_not_ready(result["fallback_reason"], gate="route_not_promoted")
            return result

        max_share_pct = thresholds.max_route_share_pct(mapped_strategy)
        route_share_cap_pct = max_share_pct
        if max_share_pct is not None:
            current_share = _route_share_pct(snapshot, mapped_strategy)
            route_share_pct = current_share
            if current_share is not None and current_share >= max_share_pct:
                result["auto_fallback_reason"] = "route_share_cap"
                result["fallback_reason"] = f"route_share_cap:{current_share:.2f}%>={max_share_pct:.2f}%"
                _mark_not_ready(result["fallback_reason"], gate="route_share_cap")
                return result

    if suggested_regime == SUGGESTED_REGIME_UNKNOWN:
        result["auto_fallback_reason"] = "mixed_or_unclear_regime"
        result["fallback_reason"] = result["auto_fallback_reason"]
    elif suggested_regime == SUGGESTED_REGIME_CHOPPY:
        result["auto_fallback_reason"] = "choppy_market"
        result["fallback_reason"] = result["auto_fallback_reason"]
    elif suggested_regime == SUGGESTED_REGIME_TREND_DOWN:
        result["auto_fallback_reason"] = "downtrend_observe_only"
        result["fallback_reason"] = result["auto_fallback_reason"]
    elif suggested_regime == SUGGESTED_REGIME_BREAKOUT_DOWN:
        result["auto_fallback_reason"] = "breakout_down_observe_only"
        result["fallback_reason"] = result["auto_fallback_reason"]
    elif suggested_regime == SUGGESTED_REGIME_VOLATILE:
        if mapped_strategy == STRATEGY_BREAKOUT_MOMENTUM:
            result["auto_fallback_reason"] = "volatile_breakout_override"
            result["fallback_reason"] = result["auto_fallback_reason"]
        else:
            result["auto_fallback_reason"] = "volatile_observe_only"
            result["fallback_reason"] = result["auto_fallback_reason"]

    result["effective_strategy"] = mapped_strategy
    result["effective_route"] = mapped_strategy
    if detection_timestamp is not None and result["route_timestamp_age_seconds"] is None:
        route_age = max(0.0, route_eval_ts - detection_timestamp)
        result["route_timestamp_age_seconds"] = route_age
        result["route_timestamp_fresh"] = route_age <= max_route_age_seconds
    if mapped_strategy in {STRATEGY_TREND_PULLBACK, STRATEGY_BREAKOUT_MOMENTUM}:
        _mark_ready("auto_quality_gates_passed")
    elif mapped_strategy == STRATEGY_OBSERVE_ONLY:
        _mark_not_ready(result.get("fallback_reason") or "observe_only_regime", gate="observe_only_regime")
    else:
        _mark_not_ready(result.get("fallback_reason") or "mean_reversion_fallback", gate="mean_reversion_fallback")
    _sync_decision_diagnostics()
    return result
