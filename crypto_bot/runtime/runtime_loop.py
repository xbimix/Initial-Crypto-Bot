from __future__ import annotations


def infer_blocked_reason(
    *,
    executed: bool,
    blocked_reason: str | None,
    execution_report: dict | None,
) -> str | None:
    if executed or blocked_reason:
        return blocked_reason
    if not isinstance(execution_report, dict):
        return blocked_reason
    raw = execution_report.get("reason")
    if raw is None:
        return blocked_reason
    reason = str(raw).strip()
    return reason or blocked_reason

