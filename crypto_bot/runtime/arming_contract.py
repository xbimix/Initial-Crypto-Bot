from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeArmingContract:
    deployed_mode: bool
    execution_mode: str
    token_configured: bool
    strict_mutating_auth: bool
    deployed_mutations_enabled: bool
    deployed_live_arming_enabled: bool
    mutating_allowed: bool
    live_arming_allowed: bool
    failures: tuple[str, ...]
    live_arming_failures: tuple[str, ...]


def normalize_execution_mode(value: object) -> str:
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw:
            return raw
    return "paper"


def evaluate_runtime_arming_contract(
    *,
    deployed_mode: bool,
    execution_mode: str,
    token_configured: bool,
    strict_mutating_auth: bool,
    deployed_mutations_enabled: bool,
    deployed_live_arming_enabled: bool,
) -> RuntimeArmingContract:
    normalized_mode = normalize_execution_mode(execution_mode)

    failures: list[str] = []
    if not token_configured:
        failures.append("missing_auth_token")
    if deployed_mode and not strict_mutating_auth:
        failures.append("strict_mutating_auth_disabled")
    if deployed_mode and not deployed_mutations_enabled:
        failures.append("deployed_mutations_not_enabled")

    live_failures = list(failures)
    if deployed_mode and normalized_mode != "paper" and not deployed_live_arming_enabled:
        live_failures.append("deployed_live_arming_not_enabled")

    return RuntimeArmingContract(
        deployed_mode=bool(deployed_mode),
        execution_mode=normalized_mode,
        token_configured=bool(token_configured),
        strict_mutating_auth=bool(strict_mutating_auth),
        deployed_mutations_enabled=bool(deployed_mutations_enabled),
        deployed_live_arming_enabled=bool(deployed_live_arming_enabled),
        mutating_allowed=not failures,
        live_arming_allowed=not live_failures,
        failures=tuple(failures),
        live_arming_failures=tuple(live_failures),
    )

