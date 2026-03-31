from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from domain.contracts import FillEvent


OrderSide = Literal["BUY", "SELL"]
LiquidityRole = Literal["taker", "maker"]
ExecutionStatus = Literal["filled", "partial", "rejected", "timeout", "cancelled"]


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass(frozen=True)
class OrderIntent:
    side: OrderSide
    symbol: str
    quoted_price: float
    requested_size: float
    liquidity_role: LiquidityRole = "taker"
    cancel_after_ms: int | None = None


@dataclass(frozen=True)
class Fill:
    side: OrderSide
    price: float
    size: float
    fee_usd: float
    slippage_bps: float
    slippage_usd: float
    latency_ms: int
    reason: str | None = None


@dataclass(frozen=True)
class ExecutionContext:
    spread_bps: float = 0.0
    best_bid: float | None = None
    best_ask: float | None = None
    mid_price: float | None = None
    microprice: float | None = None
    book_imbalance: float | None = None
    momentum_norm: float | None = None
    volume_ratio: float | None = None
    data_quality_status: str | None = None
    timeout_ms: int = 2200
    enable_timeouts: bool = True
    reject_on_bad_data: bool = True

    @classmethod
    def from_trade_meta(cls, trade_meta: dict[str, Any] | None, cfg: dict[str, Any]) -> "ExecutionContext":
        meta = trade_meta if isinstance(trade_meta, dict) else {}
        return cls(
            spread_bps=max(_to_float(meta.get("spread_bps"), 0.0) or 0.0, 0.0),
            best_bid=_to_float(meta.get("best_bid"), None),
            best_ask=_to_float(meta.get("best_ask"), None),
            mid_price=_to_float(meta.get("mid_price"), None),
            microprice=_to_float(meta.get("microprice"), None),
            book_imbalance=_to_float(meta.get("book_imbalance"), None),
            momentum_norm=_to_float(meta.get("momentum_norm"), None),
            volume_ratio=_to_float(meta.get("volume_ratio"), None),
            data_quality_status=str(meta.get("data_quality_status") or "").strip().upper() or None,
            timeout_ms=max(_to_int(cfg.get("timeout_ms"), 2200), 1),
            enable_timeouts=bool(cfg.get("enable_timeouts", True)),
            reject_on_bad_data=bool(cfg.get("reject_on_bad_data", True)),
        )


@dataclass(frozen=True)
class ExecutionReport:
    status: ExecutionStatus
    side: OrderSide
    symbol: str
    quoted_price: float
    expected_fill_price: float | None
    effective_fill_price: float | None
    requested_size: float
    filled_size: float
    fill_ratio: float
    fee_usd: float
    slippage_bps: float
    slippage_usd: float
    latency_ms: int
    latency_bucket: str
    rejected: bool
    timed_out: bool
    cancelled: bool
    maker: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fill_price"] = payload["effective_fill_price"]
        return payload

    def to_fill_event(self) -> FillEvent:
        fill_price = self.effective_fill_price
        status = "rejected" if self.cancelled else self.status
        reason = self.reason
        if self.cancelled and not reason:
            reason = "cancelled"
        return FillEvent(
            status="timeout" if self.timed_out else ("rejected" if status in {"rejected", "cancelled"} else status),  # type: ignore[arg-type]
            side=self.side,
            symbol=self.symbol,
            quoted_price=self.quoted_price,
            fill_price=fill_price,
            requested_size=self.requested_size,
            filled_size=self.filled_size,
            fill_ratio=self.fill_ratio,
            fee_usd=self.fee_usd,
            slippage_bps=self.slippage_bps,
            slippage_usd=self.slippage_usd,
            latency_ms=self.latency_ms,
            latency_bucket=self.latency_bucket,
            reason=reason,
            timed_out=self.timed_out,
            rejected=self.rejected or self.cancelled,
            position_closed=False,
        )


class ExecutionSimulator:
    def __init__(self, config: dict[str, Any] | None = None):
        self.cfg = config if isinstance(config, dict) else {}

    def update_config(self, config: dict[str, Any] | None) -> None:
        self.cfg = config if isinstance(config, dict) else {}

    def _latency_bucket(self, latency_ms: int) -> str:
        if latency_ms <= 250:
            return "fast"
        if latency_ms <= 900:
            return "medium"
        return "slow"

    def _rejected(self, intent: OrderIntent, *, reason: str, timed_out: bool = False, cancelled: bool = False) -> ExecutionReport:
        status: ExecutionStatus = "timeout" if timed_out else ("cancelled" if cancelled else "rejected")
        return ExecutionReport(
            status=status,
            side=intent.side,
            symbol=intent.symbol,
            quoted_price=intent.quoted_price,
            expected_fill_price=None,
            effective_fill_price=None,
            requested_size=intent.requested_size,
            filled_size=0.0,
            fill_ratio=0.0,
            fee_usd=0.0,
            slippage_bps=0.0,
            slippage_usd=0.0,
            latency_ms=0,
            latency_bucket="none",
            rejected=not timed_out and not cancelled,
            timed_out=timed_out,
            cancelled=cancelled,
            maker=intent.liquidity_role == "maker",
            reason=reason,
        )

    def simulate(self, intent: OrderIntent, context: ExecutionContext) -> ExecutionReport:
        if intent.quoted_price <= 0 or intent.requested_size <= 0:
            return self._rejected(intent, reason="invalid_order")

        if context.reject_on_bad_data and (context.data_quality_status or "") in {
            "STALE",
            "INSUFFICIENT",
            "UNSUPPORTED_WINDOW",
        }:
            return self._rejected(intent, reason=f"bad_data:{str(context.data_quality_status or '').lower()}")

        spread_bps = max(context.spread_bps, 0.0)
        hard_reject_spread_bps = max(_to_float(self.cfg.get("hard_reject_spread_bps"), 250.0) or 250.0, 0.0)
        if hard_reject_spread_bps > 0 and spread_bps > hard_reject_spread_bps:
            return self._rejected(intent, reason="spread_too_wide")

        mid_price = context.mid_price if context.mid_price and context.mid_price > 0 else intent.quoted_price
        half_spread = (mid_price * (spread_bps / 10000.0)) / 2.0
        best_bid = context.best_bid if context.best_bid and context.best_bid > 0 else (mid_price - half_spread)
        best_ask = context.best_ask if context.best_ask and context.best_ask > 0 else (mid_price + half_spread)
        expected_fill_price = best_ask if intent.side == "BUY" else best_bid
        if expected_fill_price <= 0:
            expected_fill_price = intent.quoted_price

        requested_notional = max(expected_fill_price * intent.requested_size, 0.0)
        volume_ratio = max(context.volume_ratio or 1.0, 0.05)
        liquidity_reference_usd = max(_to_float(self.cfg.get("liquidity_reference_usd"), 5000.0) or 5000.0, 1.0)
        effective_liquidity_usd = liquidity_reference_usd * max(min(volume_ratio, 2.5), 0.25)
        notional_pressure = requested_notional / max(effective_liquidity_usd, 1.0)

        partial_trigger = max(_to_float(self.cfg.get("partial_fill_notional_pressure"), 1.0) or 1.0, 0.1)
        partial_slope = max(_to_float(self.cfg.get("partial_fill_slope"), 0.35) or 0.35, 0.0)
        min_fill_ratio = _clamp(_to_float(self.cfg.get("min_fill_ratio"), 0.20) or 0.20, 0.01, 1.0)
        reject_fill_ratio = _clamp(_to_float(self.cfg.get("reject_if_fill_ratio_below"), 0.08) or 0.08, 0.0, 1.0)
        soft_spread_bps = max(_to_float(self.cfg.get("soft_spread_bps"), 40.0) or 40.0, 1.0)
        maker_fill_decay = _clamp(_to_float(self.cfg.get("maker_fill_decay"), 0.45) or 0.45, 0.0, 1.0)

        fill_ratio = 1.0
        if notional_pressure > partial_trigger:
            fill_ratio -= (notional_pressure - partial_trigger) * partial_slope
        if spread_bps > soft_spread_bps:
            spread_penalty = min(((spread_bps - soft_spread_bps) / soft_spread_bps) * 0.25, 0.45)
            fill_ratio -= spread_penalty
        if intent.liquidity_role == "maker":
            queue_pressure = max(notional_pressure - 0.5, 0.0)
            fill_ratio -= min(queue_pressure * maker_fill_decay, 0.55)
        fill_ratio = _clamp(fill_ratio, min_fill_ratio, 1.0)

        if fill_ratio < reject_fill_ratio:
            return self._rejected(intent, reason="insufficient_liquidity")

        book_imbalance = _clamp(context.book_imbalance or 0.5, 0.0, 1.0)
        directional_imbalance = ((book_imbalance - 0.5) * 2.0) * (1.0 if intent.side == "BUY" else -1.0)
        directional_imbalance = max(directional_imbalance, 0.0)

        momentum_norm = context.momentum_norm or 0.0
        directional_momentum = momentum_norm if intent.side == "BUY" else -momentum_norm
        directional_momentum = max(directional_momentum, 0.0)

        microprice_skew_bps = 0.0
        if context.microprice is not None and expected_fill_price > 0:
            raw_delta_bps = ((context.microprice - expected_fill_price) / expected_fill_price) * 10000.0
            microprice_skew_bps = max(raw_delta_bps, 0.0) if intent.side == "BUY" else max(-raw_delta_bps, 0.0)

        base_slippage_bps = max(_to_float(self.cfg.get("base_slippage_bps"), 2.0) or 2.0, 0.0)
        spread_weight = max(_to_float(self.cfg.get("spread_slippage_weight"), 0.08) or 0.08, 0.0)
        imbalance_penalty_bps = max(_to_float(self.cfg.get("imbalance_penalty_bps"), 8.0) or 8.0, 0.0)
        momentum_penalty_bps = max(_to_float(self.cfg.get("momentum_penalty_bps"), 4.0) or 4.0, 0.0)
        microprice_weight = max(_to_float(self.cfg.get("microprice_weight"), 0.35) or 0.35, 0.0)
        participation_penalty_bps = max(_to_float(self.cfg.get("participation_penalty_bps"), 4.0) or 4.0, 0.0)
        max_slippage_bps = max(_to_float(self.cfg.get("max_slippage_bps"), 120.0) or 120.0, 0.0)
        latency_slippage_bps_per_sec = max(
            _to_float(self.cfg.get("latency_slippage_bps_per_sec"), 1.5) or 1.5,
            0.0,
        )

        latency_ms = 120
        if spread_bps > 20:
            latency_ms = 300
        if spread_bps > 60:
            latency_ms = 650
        if spread_bps > 120:
            latency_ms = 1200
        if intent.liquidity_role == "maker":
            latency_ms += max(_to_int(self.cfg.get("maker_queue_latency_ms"), 250), 0)
        latency_ms += int(max(notional_pressure - 1.0, 0.0) * max(_to_float(self.cfg.get("latency_pressure_ms"), 450) or 450.0, 0.0))
        if fill_ratio < 0.999:
            latency_ms += 200

        if context.enable_timeouts and latency_ms > max(context.timeout_ms, 1):
            return self._rejected(intent, reason="timeout", timed_out=True)
        if intent.cancel_after_ms is not None and latency_ms > max(intent.cancel_after_ms, 1):
            return self._rejected(intent, reason="cancelled_before_fill", cancelled=True)

        latency_secs = max(latency_ms, 0) / 1000.0
        slippage_bps = base_slippage_bps
        slippage_bps += spread_bps * spread_weight
        slippage_bps += directional_imbalance * imbalance_penalty_bps
        slippage_bps += directional_momentum * momentum_penalty_bps
        slippage_bps += microprice_skew_bps * microprice_weight
        slippage_bps += max(notional_pressure - 1.0, 0.0) * participation_penalty_bps
        slippage_bps += latency_secs * latency_slippage_bps_per_sec
        slippage_bps = _clamp(slippage_bps, 0.0, max_slippage_bps)

        sign = 1.0 if intent.side == "BUY" else -1.0
        effective_fill_price = expected_fill_price * (1.0 + sign * (slippage_bps / 10000.0))
        filled_size = intent.requested_size * fill_ratio

        fee_bps_key = "maker_fee_bps" if intent.liquidity_role == "maker" else "taker_fee_bps"
        fee_bps_default = 2.0 if intent.liquidity_role == "maker" else 12.0
        fee_bps = max(_to_float(self.cfg.get(fee_bps_key), fee_bps_default) or fee_bps_default, 0.0)
        fee_usd = effective_fill_price * filled_size * (fee_bps / 10000.0)
        slippage_usd = abs(effective_fill_price - expected_fill_price) * filled_size

        status: ExecutionStatus = "partial" if fill_ratio < 0.999 else "filled"
        return ExecutionReport(
            status=status,
            side=intent.side,
            symbol=intent.symbol,
            quoted_price=intent.quoted_price,
            expected_fill_price=expected_fill_price,
            effective_fill_price=effective_fill_price,
            requested_size=intent.requested_size,
            filled_size=filled_size,
            fill_ratio=fill_ratio,
            fee_usd=fee_usd,
            slippage_bps=slippage_bps,
            slippage_usd=slippage_usd,
            latency_ms=latency_ms,
            latency_bucket=self._latency_bucket(latency_ms),
            rejected=False,
            timed_out=False,
            cancelled=False,
            maker=intent.liquidity_role == "maker",
            reason=None,
        )
