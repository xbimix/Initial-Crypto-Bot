from __future__ import annotations

from strategy import strategy_runtime_state as rt
from strategy.route_metadata import inject_payload as inject_route_metadata_payload


def build_decision_payload(
    *,
    symbol,
    action,
    price,
    momentum,
    reason,
    logger,
    record_buy_block_gate,
):
    logger.info(f"{symbol} -> {action} | reason={reason}")
    record_buy_block_gate(symbol=symbol, action=action, reason=reason)
    payload = {
        "symbol": symbol,
        "action": action,
        "price": price,
        "momentum": momentum,
        "reason": reason,
    }
    if symbol in rt._last_regime:
        payload["regime"] = rt._last_regime[symbol]
    if symbol in rt._last_score:
        payload["score"] = rt._last_score[symbol]
    if symbol in rt._last_volatility:
        payload["volatility"] = rt._last_volatility[symbol]
    if symbol in rt._entry_route:
        payload["entry_route"] = rt._entry_route[symbol]
    if symbol in rt._entry_regime:
        payload["entry_regime"] = rt._entry_regime[symbol]
    if symbol in rt._exit_policy:
        payload["exit_policy"] = rt._exit_policy[symbol]
    if symbol in rt._entry_confidence:
        payload["entry_confidence"] = rt._entry_confidence[symbol]
    if symbol in rt._entry_timestamp:
        payload["entry_timestamp"] = rt._entry_timestamp[symbol]
    if symbol in rt._entry_route_eval_ts:
        payload["entry_route_eval_ts"] = rt._entry_route_eval_ts[symbol]
    if symbol in rt._entry_regime_eval_ts:
        payload["entry_regime_eval_ts"] = rt._entry_regime_eval_ts[symbol]
    if symbol in rt._last_buy_block_reason:
        payload["last_buy_block_reason"] = rt._last_buy_block_reason[symbol]
    if symbol in rt._last_buy_block_route:
        payload["last_buy_block_route"] = rt._last_buy_block_route[symbol]
    inject_route_metadata_payload(symbol, payload, rt.ROUTE_METADATA_MAPS)
    return payload
