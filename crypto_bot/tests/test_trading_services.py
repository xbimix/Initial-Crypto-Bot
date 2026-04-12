from __future__ import annotations

from domain.contracts import DecisionIntent
from trading.services import (
    DecisionService,
    ExecutionService,
    PortfolioStateService,
    RiskGateService,
)


class _FakeRisk:
    def __init__(self):
        self.registered: list[tuple[str, dict]] = []
        self.closed: list[str] = []

    def is_within_trade_window(self):
        return True

    def daily_loss_state(self):
        return {"buy_paused": False}

    def can_trade(self, *_args, **_kwargs):
        return True

    def can_open_position(self, *_args, **_kwargs):
        return True

    def can_open_position_for_symbol(self, *_args, **_kwargs):
        return True

    def can_open_under_max_trade_amount(self, *_args, **_kwargs):
        return True

    def exposure_block_reason(self, *_args, **_kwargs):
        return None

    def register_position(self, symbol: str, payload: dict):
        self.registered.append((symbol, payload))

    def close_position(self, symbol: str):
        self.closed.append(symbol)

    def mark_trade(self, *_args, **_kwargs):
        return None


class _FakeLogger:
    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None


class _FakePaper:
    def __init__(self):
        self.positions = {
            "BTC-USD": {"price": 100.0, "size": 2.0, "entry_time": 123},
            "ETH-USD": {"price": 50.0, "size": 1.0, "entry_time": 124},
        }
        self.last_execution_report: dict = {}

    def get_position(self, symbol: str):
        return self.positions.get(symbol)

    def buy(self, *_args, **_kwargs):
        self.last_execution_report = {"status": "filled", "fill_price": 100.2}
        return True

    def sell(self, *_args, **_kwargs):
        self.last_execution_report = {"status": "partial", "position_closed": False}
        return True


def test_decision_service_builds_context_with_market_meta():
    context = DecisionService.build_context(
        {
            "symbol": "btc-usd",
            "action": "buy",
            "price": 101.0,
            "entry_route": "trend_pullback",
        },
        {
            "symbol": "BTC-USD",
            "price": 101.0,
            "spread_bps": 8.0,
            "data_quality_status": "good",
        },
    )
    assert context.intent.symbol == "BTC-USD"
    assert context.trade_meta["entry_route"] == "trend_pullback"
    assert context.trade_meta["spread_bps"] == 8.0
    assert context.trade_meta["data_quality_status"] == "GOOD"


def test_decision_service_validation_error_on_bad_price():
    intent = DecisionIntent.from_payload({"symbol": "BTC-USD", "action": "BUY", "price": 0})
    assert DecisionService.validation_error(intent) == "invalid_decision_price"


def test_decision_intent_accepts_confidence_score_alias():
    intent = DecisionIntent.from_payload(
        {"symbol": "BTC-USD", "action": "BUY", "price": 100.0, "detected_regime_confidence_score": 77.5}
    )
    assert intent.entry_confidence == 77.5


def test_risk_gate_blocks_bad_market_quality():
    gate = RiskGateService(_FakeRisk(), _FakeLogger())
    reason = gate.check_buy_preconditions(
        cfg={"risk": {"block_bad_market_quality": True}},
        symbol="BTC-USD",
        volatility=0.01,
        trade_meta={"data_quality_status": "STALE"},
        open_positions_count=0,
        symbol_open_positions=0,
        has_open_position=False,
    )
    assert reason == "bad_market_quality:stale"


def test_execution_service_returns_report_copy():
    paper = _FakePaper()
    svc = ExecutionService(paper)
    ok, report = svc.execute_buy(
        symbol="BTC-USD",
        price=100.0,
        size=1.0,
        reason="test",
    )
    report["status"] = "mutated"
    assert ok is True
    assert paper.last_execution_report["status"] == "filled"


def test_portfolio_state_service_tracks_allocated_and_partial_sell():
    risk = _FakeRisk()
    svc = PortfolioStateService(_FakePaper(), risk, _FakeLogger())
    allocated, per_symbol = svc.current_allocated_usd()
    assert allocated == 250.0
    assert per_symbol["BTC-USD"] == 200.0

    still_open = svc.register_sell_fill(
        symbol="BTC-USD",
        execution_report={"position_closed": False},
    )
    assert still_open is False
    assert risk.closed == []
    assert risk.registered[-1][0] == "BTC-USD"
