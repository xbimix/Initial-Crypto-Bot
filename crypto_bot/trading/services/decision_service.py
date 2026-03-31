from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from domain.contracts import DecisionIntent, MarketSnapshot


@dataclass(frozen=True)
class DecisionContext:
    intent: DecisionIntent
    market_snapshot: MarketSnapshot | None
    volatility: float | None
    trade_meta: dict[str, Any]


class DecisionService:
    @staticmethod
    def build_context(decision: dict | None, market: dict | None) -> DecisionContext:
        safe_decision = decision if isinstance(decision, dict) else {}
        intent = DecisionIntent.from_payload(safe_decision)
        market_snapshot = MarketSnapshot.from_payload(market if isinstance(market, dict) else None)
        trade_meta = {
            "effective_route": safe_decision.get("effective_route"),
            "effective_strategy": safe_decision.get("effective_strategy"),
            "configured_regime": safe_decision.get("configured_regime"),
            "detected_regime": safe_decision.get("detected_regime"),
            "suggested_regime_v2": safe_decision.get("suggested_regime_v2"),
            "fallback_reason": safe_decision.get("fallback_reason"),
            "auto_fallback_reason": safe_decision.get("auto_fallback_reason"),
            "entry_route": intent.entry_route or intent.effective_route or safe_decision.get("effective_route"),
            "entry_regime": intent.entry_regime or safe_decision.get("suggested_regime_v2") or safe_decision.get("detected_regime"),
            "exit_policy": intent.exit_policy or safe_decision.get("exit_policy"),
            "entry_confidence": intent.entry_confidence,
            "entry_timestamp": safe_decision.get("entry_timestamp"),
            "route_eval_ts": safe_decision.get("entry_route_eval_ts") or safe_decision.get("route_eval_ts"),
            "regime_eval_ts": safe_decision.get("entry_regime_eval_ts") or safe_decision.get("regime_eval_ts"),
            "expected_edge_bps": intent.expected_edge_bps,
            "expected_hold_seconds": intent.expected_hold_seconds,
            "decision_ts_epoch": intent.decision_ts_epoch or time.time(),
        }
        if market_snapshot is not None:
            trade_meta.update(market_snapshot.to_meta())
        return DecisionContext(
            intent=intent,
            market_snapshot=market_snapshot,
            volatility=safe_decision.get("volatility"),
            trade_meta=trade_meta,
        )

    @staticmethod
    def validation_error(intent: DecisionIntent) -> str | None:
        if not intent.symbol or intent.action not in {"BUY", "SELL", "HOLD"}:
            return "invalid_decision_payload"
        if intent.price <= 0:
            return "invalid_decision_price"
        return None

    @staticmethod
    def enrich_sell_trade_meta(position: dict | None, trade_meta: dict | None) -> dict:
        merged = dict(trade_meta) if isinstance(trade_meta, dict) else {}
        pos = position if isinstance(position, dict) else {}
        merged.setdefault("entry_route", pos.get("entry_route"))
        merged.setdefault("entry_regime", pos.get("entry_regime"))
        merged.setdefault("exit_policy", pos.get("exit_policy"))
        merged.setdefault("entry_confidence", pos.get("entry_confidence"))
        merged.setdefault("entry_timestamp", pos.get("entry_timestamp"))
        merged.setdefault("route_eval_ts", pos.get("route_eval_ts"))
        merged.setdefault("regime_eval_ts", pos.get("regime_eval_ts"))
        merged.setdefault("effective_route", pos.get("entry_route"))
        merged.setdefault("exit_policy_used", pos.get("exit_policy"))
        return merged
