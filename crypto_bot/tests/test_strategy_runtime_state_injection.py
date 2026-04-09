from __future__ import annotations

from strategy import strategy_engine as se
from strategy.runtime_state_object import StrategyRuntimeState


def test_evaluate_symbol_injects_runtime_state_object(monkeypatch):
    captured = {}

    def _fake_impl(snapshot, cfg, *, ctx, runtime_state=None):
        captured["runtime_state"] = runtime_state
        return {"symbol": snapshot["symbol"], "action": "HOLD", "reason": "stubbed"}

    monkeypatch.setattr(se, "_evaluate_symbol_impl", _fake_impl)
    result = se.evaluate_symbol({"symbol": "TEST-USD"}, {})
    assert result["reason"] == "stubbed"
    assert isinstance(captured.get("runtime_state"), StrategyRuntimeState)


def test_runtime_state_compat_exports_map_to_canonical_state():
    symbol = "TEST-USD"
    se._entry_price[symbol] = 123.45
    try:
        assert se.RUNTIME_STATE._entry_price[symbol] == 123.45
    finally:
        se._entry_price.pop(symbol, None)

