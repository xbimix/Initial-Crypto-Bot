from __future__ import annotations

from typing import Any, Callable


ROUTE_METADATA_KEYS = (
    "last_configured_regime",
    "last_detected_regime",
    "last_detected_regime_confidence",
    "last_detected_regime_confidence_label",
    "last_detected_regime_stability",
    "last_detected_regime_persistence",
    "last_detected_regime_stability_inferred",
    "last_detected_regime_persistence_inferred",
    "last_regime_data_quality_status",
    "last_regime_key_windows_supported",
    "last_suggested_regime_v2",
    "last_detection_source",
    "last_detection_timestamp_epoch",
    "last_effective_strategy",
    "last_effective_route",
    "last_route_eval_ts",
    "last_regime_eval_ts",
    "last_auto_fallback_reason",
    "last_fallback_reason",
    "last_ready_for_non_mr_route",
    "last_non_mr_ready_reason",
    "last_route_readiness_state",
    "last_route_timestamp_age_seconds",
    "last_route_timestamp_fresh",
    "last_shadow_continuity_state",
    "last_shadow_age_seconds",
    "last_failed_gates",
    "last_decision_diagnostics",
)


def _update_optional(
    target: dict[str, Any],
    symbol: str,
    value: Any,
    *,
    validator: Callable[[Any], bool] | None = None,
) -> bool:
    if validator is not None and not validator(value):
        if symbol in target:
            target.pop(symbol, None)
            return True
        return False
    if target.get(symbol) != value:
        target[symbol] = value
        return True
    return False


def state_map(route_maps: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {key: route_maps[key] for key in ROUTE_METADATA_KEYS}


def record_route_metadata(
    *,
    symbol: str,
    route: dict[str, Any],
    route_maps: dict[str, dict[str, Any]],
    parse_numeric: Callable[[Any, Any], float | None],
) -> bool:
    configured = route.get("configured_regime")
    detected = route.get("detected_regime")
    detected_confidence = parse_numeric(
        route.get("detected_regime_confidence", route.get("detected_regime_confidence_score")),
        None,
    )
    detected_confidence_label = route.get("detected_regime_confidence_label")
    detected_stability = parse_numeric(
        route.get("detected_regime_stability", route.get("detected_regime_stability_score")),
        None,
    )
    detected_persistence = parse_numeric(
        route.get("detected_regime_persistence", route.get("detected_regime_persistence_score")),
        None,
    )
    detected_stability_inferred = route.get("detected_regime_stability_inferred")
    detected_persistence_inferred = route.get("detected_regime_persistence_inferred")
    regime_data_quality_status = route.get("regime_data_quality_status")
    regime_key_windows_supported = route.get("regime_key_windows_supported")
    suggested_regime_v2 = route.get("suggested_regime_v2")
    detection_source = route.get("detection_source")
    detection_timestamp_epoch = parse_numeric(route.get("detection_timestamp_epoch"), None)
    effective_strategy = route.get("effective_strategy")
    effective_route = route.get("effective_route")
    route_eval_ts = parse_numeric(route.get("route_eval_ts"), None)
    regime_eval_ts = parse_numeric(route.get("regime_eval_ts"), None)
    fallback_reason = route.get("auto_fallback_reason")
    fallback_reason_v2 = route.get("fallback_reason")
    ready_for_non_mr_route = route.get("ready_for_non_mr_route")
    non_mr_ready_reason = route.get("non_mr_ready_reason")
    route_readiness_state = route.get("route_readiness_state")
    route_timestamp_age_seconds = parse_numeric(route.get("route_timestamp_age_seconds"), None)
    route_timestamp_fresh = route.get("route_timestamp_fresh")
    shadow_continuity_state = route.get("shadow_continuity_state")
    shadow_age_seconds = parse_numeric(route.get("shadow_age_seconds"), None)
    failed_gates = route.get("failed_gates")
    decision_diagnostics = route.get("decision_diagnostics")

    changed = False
    changed |= _update_optional(route_maps["last_configured_regime"], symbol, configured, validator=lambda x: isinstance(x, str) and bool(x))
    changed |= _update_optional(route_maps["last_detected_regime"], symbol, detected, validator=lambda x: isinstance(x, str) and bool(x))
    changed |= _update_optional(route_maps["last_detected_regime_confidence"], symbol, detected_confidence)
    changed |= _update_optional(
        route_maps["last_detected_regime_confidence_label"],
        symbol,
        detected_confidence_label,
        validator=lambda x: isinstance(x, str) and bool(x),
    )
    changed |= _update_optional(route_maps["last_detected_regime_stability"], symbol, detected_stability)
    changed |= _update_optional(route_maps["last_detected_regime_persistence"], symbol, detected_persistence)
    changed |= _update_optional(
        route_maps["last_detected_regime_stability_inferred"],
        symbol,
        detected_stability_inferred,
        validator=lambda x: isinstance(x, bool),
    )
    changed |= _update_optional(
        route_maps["last_detected_regime_persistence_inferred"],
        symbol,
        detected_persistence_inferred,
        validator=lambda x: isinstance(x, bool),
    )
    changed |= _update_optional(
        route_maps["last_regime_data_quality_status"],
        symbol,
        regime_data_quality_status,
        validator=lambda x: isinstance(x, str) and bool(x),
    )
    changed |= _update_optional(
        route_maps["last_regime_key_windows_supported"],
        symbol,
        regime_key_windows_supported,
        validator=lambda x: isinstance(x, bool),
    )
    changed |= _update_optional(
        route_maps["last_suggested_regime_v2"],
        symbol,
        suggested_regime_v2,
        validator=lambda x: isinstance(x, str) and bool(x),
    )
    changed |= _update_optional(
        route_maps["last_detection_source"],
        symbol,
        detection_source,
        validator=lambda x: isinstance(x, str) and bool(x),
    )
    changed |= _update_optional(route_maps["last_detection_timestamp_epoch"], symbol, detection_timestamp_epoch)
    changed |= _update_optional(
        route_maps["last_effective_strategy"],
        symbol,
        effective_strategy,
        validator=lambda x: isinstance(x, str) and bool(x),
    )

    resolved_effective_route = effective_route
    if not (isinstance(resolved_effective_route, str) and resolved_effective_route):
        if isinstance(effective_strategy, str) and effective_strategy:
            resolved_effective_route = effective_strategy
    changed |= _update_optional(
        route_maps["last_effective_route"],
        symbol,
        resolved_effective_route,
        validator=lambda x: isinstance(x, str) and bool(x),
    )
    changed |= _update_optional(route_maps["last_route_eval_ts"], symbol, route_eval_ts)
    changed |= _update_optional(route_maps["last_regime_eval_ts"], symbol, regime_eval_ts)
    changed |= _update_optional(
        route_maps["last_auto_fallback_reason"],
        symbol,
        fallback_reason,
        validator=lambda x: isinstance(x, str) and bool(x),
    )

    fallback_combined = fallback_reason_v2
    if not (isinstance(fallback_combined, str) and fallback_combined):
        fallback_combined = fallback_reason
    changed |= _update_optional(
        route_maps["last_fallback_reason"],
        symbol,
        fallback_combined,
        validator=lambda x: isinstance(x, str) and bool(x),
    )
    changed |= _update_optional(
        route_maps["last_ready_for_non_mr_route"],
        symbol,
        ready_for_non_mr_route,
        validator=lambda x: isinstance(x, bool),
    )
    changed |= _update_optional(
        route_maps["last_non_mr_ready_reason"],
        symbol,
        non_mr_ready_reason,
        validator=lambda x: isinstance(x, str) and bool(x),
    )
    changed |= _update_optional(
        route_maps["last_route_readiness_state"],
        symbol,
        route_readiness_state,
        validator=lambda x: isinstance(x, str) and bool(x),
    )
    changed |= _update_optional(route_maps["last_route_timestamp_age_seconds"], symbol, route_timestamp_age_seconds)
    changed |= _update_optional(
        route_maps["last_route_timestamp_fresh"],
        symbol,
        route_timestamp_fresh,
        validator=lambda x: isinstance(x, bool),
    )
    changed |= _update_optional(
        route_maps["last_shadow_continuity_state"],
        symbol,
        shadow_continuity_state,
        validator=lambda x: isinstance(x, str) and bool(x),
    )
    changed |= _update_optional(route_maps["last_shadow_age_seconds"], symbol, shadow_age_seconds)
    changed |= _update_optional(
        route_maps["last_failed_gates"],
        symbol,
        failed_gates,
        validator=lambda x: isinstance(x, list),
    )
    changed |= _update_optional(
        route_maps["last_decision_diagnostics"],
        symbol,
        decision_diagnostics,
        validator=lambda x: isinstance(x, dict),
    )
    return changed


def cleanup_symbol(symbol: str, route_maps: dict[str, dict[str, Any]]) -> None:
    for key in ROUTE_METADATA_KEYS:
        route_maps[key].pop(symbol, None)


def inject_payload(symbol: str, payload: dict[str, Any], route_maps: dict[str, dict[str, Any]]) -> None:
    for key in ROUTE_METADATA_KEYS:
        symbol_map = route_maps[key]
        if symbol in symbol_map:
            payload[key.replace("last_", "")] = symbol_map[symbol]
    confidence = payload.get("detected_regime_confidence")
    if confidence is not None:
        payload.setdefault("detected_regime_confidence_score", confidence)
    stability = payload.get("detected_regime_stability")
    if stability is not None:
        payload.setdefault("detected_regime_stability_score", stability)
    persistence = payload.get("detected_regime_persistence")
    if persistence is not None:
        payload.setdefault("detected_regime_persistence_score", persistence)
