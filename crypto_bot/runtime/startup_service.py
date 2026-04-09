from __future__ import annotations


def has_critical_startup_failure(status: dict) -> bool:
    checks = status.get("checks", [])
    if not isinstance(checks, list):
        return False
    return any(
        isinstance(item, dict) and not item.get("ok", True) and bool(item.get("critical", False))
        for item in checks
    )


def log_startup_checks(logger, result: dict):
    if result.get("ok"):
        logger.info("Startup checks passed")
        return
    logger.warning(f"Startup checks reported issues: {result.get('checks', [])}")

