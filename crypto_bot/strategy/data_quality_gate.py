from __future__ import annotations

from typing import Any


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
    return default


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed:  # NaN guard
        return default
    return parsed


def evaluate_entry_data_quality(
    *,
    snapshot: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """
    Resolve whether a route may evaluate entry logic under current data quality.

    Default behavior remains strict/backward-compatible: `data_quality_ok` must
    be True. A controlled score-floor participation path is available only when
    explicitly enabled in config.
    """
    data_quality_ok = snapshot.get("data_quality_ok")
    if data_quality_ok is True:
        return True, None

    reason = snapshot.get("data_quality_reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = "data_quality_missing" if data_quality_ok is None else "data_quality_failed"
    fallback_reason = str(reason)

    config = cfg if isinstance(cfg, dict) else {}
    market_data_cfg = config.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        market_data_cfg = {}
    allow_partial = _as_bool(
        market_data_cfg.get("strategy_allow_partial_participation", False),
        False,
    )
    if not allow_partial:
        return False, fallback_reason

    status = str(snapshot.get("data_quality_status") or "").strip().upper()
    if status not in {"GOOD", "PARTIAL"}:
        return False, fallback_reason

    quality_score = _as_float(snapshot.get("data_quality_score"), None)
    if quality_score is None:
        return False, fallback_reason

    min_quality_score = _as_float(
        market_data_cfg.get("strategy_eval_min_quality_score", 0.0),
        0.0,
    ) or 0.0
    if min_quality_score <= 0:
        return False, fallback_reason
    if float(quality_score) < float(min_quality_score):
        return False, fallback_reason

    return True, "partial_quality_score_floor"

