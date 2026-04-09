from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class StrategyEvalGate:
    allowed: bool
    blocked_reason: str | None = None
    snapshot_age_seconds: float | None = None
    quality_status: str | None = None
    quality_state: str | None = None
    quality_score: float | None = None
    core_ready: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": bool(self.allowed),
            "blocked_reason": self.blocked_reason,
            "snapshot_age_seconds": self.snapshot_age_seconds,
            "quality_status": self.quality_status,
            "quality_state": self.quality_state,
            "quality_score": self.quality_score,
            "core_ready": self.core_ready,
        }


@dataclass(frozen=True)
class NormalizedMarketSnapshot:
    symbol: str
    payload: dict[str, Any]
    snapshot_version: int
    field_timestamps: dict[str, float] = field(default_factory=dict)
    quality_state: str = "UNKNOWN"
    strategy_eval_gate: StrategyEvalGate = field(default_factory=lambda: StrategyEvalGate(allowed=True))

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        snapshot_version: int,
        field_timestamps: Mapping[str, float] | None = None,
        quality_state: str = "UNKNOWN",
        strategy_eval_gate: StrategyEvalGate | None = None,
    ) -> "NormalizedMarketSnapshot":
        symbol = str(payload.get("symbol") or "").strip().upper()
        return cls(
            symbol=symbol,
            payload=dict(payload),
            snapshot_version=max(int(snapshot_version), 1),
            field_timestamps=dict(field_timestamps or {}),
            quality_state=str(quality_state or "UNKNOWN").strip().upper() or "UNKNOWN",
            strategy_eval_gate=strategy_eval_gate or StrategyEvalGate(allowed=True),
        )

    def to_legacy_dict(self) -> dict[str, Any]:
        row = dict(self.payload)
        row["snapshot_version"] = int(self.snapshot_version)
        row["snapshot_field_timestamps"] = dict(self.field_timestamps)
        row["data_quality_state"] = str(self.quality_state)
        row["strategy_eval_gate"] = self.strategy_eval_gate.to_dict()
        row["strategy_eval_allowed"] = bool(self.strategy_eval_gate.allowed)
        return row


@dataclass(frozen=True)
class DecisionInput:
    symbol: str
    price: float
    snapshot_version: int
    data_quality_status: str
    strategy_eval_allowed: bool
    payload: dict[str, Any]

    @classmethod
    def from_snapshot_payload(cls, payload: Mapping[str, Any]) -> "DecisionInput | None":
        symbol = str(payload.get("symbol") or "").strip().upper()
        price = _to_float(payload.get("price"), None)
        if not symbol or price is None or price <= 0:
            return None
        return cls(
            symbol=symbol,
            price=price,
            snapshot_version=_to_int(payload.get("snapshot_version"), 1) or 1,
            data_quality_status=str(payload.get("data_quality_status") or "UNKNOWN").strip().upper(),
            strategy_eval_allowed=bool(payload.get("strategy_eval_allowed", True)),
            payload=dict(payload),
        )

    def to_strategy_payload(self) -> dict[str, Any]:
        return dict(self.payload)
