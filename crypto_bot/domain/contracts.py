from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


Action = Literal["BUY", "SELL", "HOLD"]
Side = Literal["BUY", "SELL"]
FillStatus = Literal["filled", "partial", "timeout", "rejected"]


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    price: float
    spread_bps: float | None = None
    spread: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    mid_price: float | None = None
    microprice: float | None = None
    book_imbalance: float | None = None
    momentum_norm: float | None = None
    atr_raw: float | None = None
    volume_ratio: float | None = None
    data_quality_status: str | None = None
    snapshot_ts_epoch: float | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "MarketSnapshot | None":
        if not isinstance(payload, dict):
            return None
        symbol = str(payload.get("symbol") or "").strip().upper()
        price = _to_float(payload.get("price"), None)
        if not symbol or price is None or price <= 0:
            return None
        return cls(
            symbol=symbol,
            price=price,
            spread_bps=_to_float(payload.get("spread_bps"), None),
            spread=_to_float(payload.get("spread"), None),
            best_bid=_to_float(payload.get("best_bid"), None),
            best_ask=_to_float(payload.get("best_ask"), None),
            mid_price=_to_float(payload.get("mid_price"), None),
            microprice=_to_float(payload.get("microprice"), None),
            book_imbalance=_to_float(payload.get("book_imbalance"), None),
            momentum_norm=_to_float(payload.get("momentum_norm"), None),
            atr_raw=_to_float(payload.get("atr_raw"), None),
            volume_ratio=_to_float(payload.get("volume_ratio"), None),
            data_quality_status=str(payload.get("data_quality_status") or "").strip().upper() or None,
            snapshot_ts_epoch=_to_float(payload.get("snapshot_ts_epoch"), None),
        )

    def to_meta(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionIntent:
    symbol: str
    action: Action
    price: float
    reason: str
    effective_route: str | None = None
    effective_strategy: str | None = None
    entry_route: str | None = None
    entry_regime: str | None = None
    exit_policy: str | None = None
    entry_confidence: float | None = None
    expected_edge_bps: float | None = None
    expected_hold_seconds: float | None = None
    decision_ts_epoch: float | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DecisionIntent":
        symbol = str(payload.get("symbol") or "").strip().upper()
        action = str(payload.get("action") or "").strip().upper()
        if action not in {"BUY", "SELL", "HOLD"}:
            action = "HOLD"
        price = _to_float(payload.get("price"), 0.0) or 0.0
        return cls(
            symbol=symbol,
            action=action,  # type: ignore[arg-type]
            price=price,
            reason=str(payload.get("reason") or "").strip() or "unspecified",
            effective_route=str(payload.get("effective_route") or "").strip().lower() or None,
            effective_strategy=str(payload.get("effective_strategy") or "").strip().lower() or None,
            entry_route=str(payload.get("entry_route") or "").strip().lower() or None,
            entry_regime=str(payload.get("entry_regime") or "").strip().lower() or None,
            exit_policy=str(payload.get("exit_policy") or "").strip().lower() or None,
            entry_confidence=_to_float(
                payload.get(
                    "entry_confidence",
                    payload.get(
                        "detected_regime_confidence",
                        payload.get("detected_regime_confidence_score"),
                    ),
                ),
                None,
            ),
            expected_edge_bps=_to_float(payload.get("expected_edge_bps"), None),
            expected_hold_seconds=_to_float(payload.get("expected_hold_seconds"), None),
            decision_ts_epoch=_to_float(payload.get("decision_ts_epoch"), None),
        )


@dataclass(frozen=True)
class ExecutionIntent:
    side: Side
    symbol: str
    quoted_price: float
    requested_size: float
    stop_price: float | None = None
    expected_fee_bps: float | None = None
    expected_slippage_bps: float | None = None
    expected_edge_bps: float | None = None
    expected_hold_seconds: float | None = None


@dataclass(frozen=True)
class FillEvent:
    status: FillStatus
    side: Side
    symbol: str
    quoted_price: float
    fill_price: float | None
    requested_size: float
    filled_size: float
    fill_ratio: float
    fee_usd: float
    slippage_bps: float
    slippage_usd: float
    latency_ms: int
    latency_bucket: str
    reason: str | None
    timed_out: bool
    rejected: bool
    position_closed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RiskCheckResult:
    allowed: bool
    reason: str | None = None
