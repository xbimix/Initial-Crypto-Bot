from __future__ import annotations

from typing import Any


def parse_kill_reason(body: Any) -> str | None:
    if isinstance(body, dict):
        value = body.get("reason")
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
        return value
    return None


def apply_kill_request(
    *,
    body: Any,
    apply_control_action_response,
    apply_control_action,
) -> tuple[str | None, dict | None, dict | None]:
    reason = parse_kill_reason(body)
    payload, error = apply_control_action_response(
        action="KILL",
        reason=reason,
        apply_control_action=apply_control_action,
    )
    return reason, payload, error
