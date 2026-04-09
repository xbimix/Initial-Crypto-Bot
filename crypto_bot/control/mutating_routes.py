from __future__ import annotations

from collections.abc import Callable
from typing import Any


def apply_config_update(
    *,
    updates: dict[str, Any],
    load_config: Callable[[], dict],
    update_config: Callable[[Callable[[dict], dict]], dict],
    logger,
) -> tuple[dict, dict, dict]:
    before_cfg = load_config()
    old_values = {
        key: before_cfg.get(key)
        for key in updates.keys()
    } if isinstance(before_cfg, dict) else {}

    def _mutate(cfg):
        cfg.update(updates)
        return cfg

    cfg = update_config(_mutate)
    logger.info(f"Config updated: {updates}")
    return cfg, old_values, updates


def apply_control_action_response(
    *,
    action: str,
    reason: str | None,
    apply_control_action: Callable[..., tuple[dict | None, str | dict | None]],
) -> tuple[dict | None, dict | None]:
    payload, error = apply_control_action(action, reason=reason)
    if error:
        if isinstance(error, dict):
            return None, {
                "message": error.get("message") or "control action blocked",
                "status": int(error.get("status", 400) or 400),
                "code": str(error.get("code", "bad_request")),
                "details": error.get("details"),
            }
        return None, {
            "message": str(error),
            "status": 400,
            "code": "bad_request",
            "details": None,
        }
    return payload, None


def apply_control_request(
    *,
    body: dict[str, Any],
    apply_control_action: Callable[..., tuple[dict | None, str | dict | None]],
) -> tuple[dict | None, dict | None]:
    action = str(body.get("action", ""))
    reason = body.get("reason")
    return apply_control_action_response(
        action=action,
        reason=reason,
        apply_control_action=apply_control_action,
    )
