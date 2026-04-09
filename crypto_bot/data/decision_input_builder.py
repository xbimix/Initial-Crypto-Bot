from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class DecisionContext:
    allowed: bool
    symbol: str
    blocked_reason: str | None
    audit: dict[str, Any]
    strategy_input: dict[str, Any] | None = None


def build_decision_context(snapshot: Mapping[str, Any] | None, cfg: dict | None = None) -> DecisionContext:
    payload = dict(snapshot) if isinstance(snapshot, Mapping) else {}
    symbol = str(payload.get("symbol") or "").strip().upper()
    price = _to_float(payload.get("price"), None)
    quality_status = str(payload.get("data_quality_status") or "UNKNOWN").strip().upper()
    snapshot_version = int(_to_float(payload.get("snapshot_version"), 1) or 1)
    gate = payload.get("strategy_eval_gate", {})
    gate_allowed = bool(gate.get("allowed", True)) if isinstance(gate, Mapping) else True
    gate_reason = str(gate.get("blocked_reason") or "").strip() if isinstance(gate, Mapping) else ""
    gate_snapshot_age_seconds = _to_float(gate.get("snapshot_age_seconds"), None) if isinstance(gate, Mapping) else None

    blocked_reason: str | None = None
    if not symbol:
        blocked_reason = "missing_symbol"
    elif price is None or price <= 0:
        blocked_reason = "invalid_price"
    elif not gate_allowed:
        blocked_reason = gate_reason or "strategy_eval_gate_blocked"

    market_cfg = {}
    if isinstance(cfg, dict):
        candidate = cfg.get("market_data", {})
        if isinstance(candidate, dict):
            market_cfg = candidate
    strict_required = bool(market_cfg.get("decision_context_require_quality", False))
    if blocked_reason is None and strict_required and quality_status in {"UNKNOWN", "PARTIAL"}:
        blocked_reason = f"insufficient_decision_quality:{quality_status.lower()}"

    audit = {
        "snapshot_version": snapshot_version,
        "data_quality_status": quality_status,
        "strategy_eval_allowed": blocked_reason is None,
        "blocked_reason": blocked_reason,
        "market_snapshot_ts_epoch": _to_float(payload.get("snapshot_ts_epoch"), None),
        "market_snapshot_age_seconds": gate_snapshot_age_seconds,
        "candle_timeframe": payload.get("candle_timeframe"),
        "candle_last_update_ts": payload.get("candle_last_update_ts"),
        "candle_age_seconds": _to_float(payload.get("candle_age_seconds"), None),
        "candle_stale_after_seconds": _to_float(payload.get("candle_stale_after_seconds"), None),
        "candle_age_over_stale_ratio": _to_float(payload.get("candle_age_over_stale_ratio"), None),
        "data_quality_score": _to_float(payload.get("data_quality_score"), None),
    }
    return DecisionContext(
        allowed=blocked_reason is None,
        symbol=symbol,
        blocked_reason=blocked_reason,
        audit=audit,
        strategy_input=(payload if blocked_reason is None else None),
    )
