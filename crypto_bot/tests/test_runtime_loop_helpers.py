from runtime.runtime_loop import infer_blocked_reason
from runtime.startup_service import has_critical_startup_failure


def test_infer_blocked_reason_uses_execution_report_reason_when_missing():
    reason = infer_blocked_reason(
        executed=False,
        blocked_reason=None,
        execution_report={"status": "rejected", "reason": "freshness_slo_degraded"},
    )
    assert reason == "freshness_slo_degraded"


def test_infer_blocked_reason_preserves_existing_reason():
    reason = infer_blocked_reason(
        executed=False,
        blocked_reason="signal_confirmation",
        execution_report={"reason": "runtime_override"},
    )
    assert reason == "signal_confirmation"


def test_has_critical_startup_failure_detects_only_critical_flags():
    assert (
        has_critical_startup_failure(
            {"checks": [{"name": "noncritical", "ok": False, "critical": False}]}
        )
        is False
    )
    assert (
        has_critical_startup_failure(
            {"checks": [{"name": "critical", "ok": False, "critical": True}]}
        )
        is True
    )
