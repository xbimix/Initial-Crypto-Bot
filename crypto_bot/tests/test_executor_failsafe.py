from __future__ import annotations

import time

from risk.risk_manager import PositionSizingResult
from trading.executor import Executor


class _FakePaper:
    def __init__(self):
        self.positions: dict[str, dict] = {}
        self.last_execution_report: dict = {}
        self.buy_calls = 0

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def get_balance(self) -> float:
        return 10000.0

    def preview_execution_cost_bps(self, **_kwargs):
        return {"fee_bps": 0.0, "slippage_bps": 0.0, "total_cost_bps": 0.0}

    def buy(self, *_args, **_kwargs):
        self.buy_calls += 1
        self.last_execution_report = {"status": "rejected", "reason": "timeout"}
        return False

    def get_position(self, _symbol: str):
        return None


class _FakeRisk:
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

    def position_sizing(self, *_args, **_kwargs):
        return PositionSizingResult(
            mode="stop_distance",
            raw_size=1.0,
            capped_size=1.0,
            risk_budget_used_usd=100.0,
            stop_distance=1.0,
            per_unit_risk_usd=1.0,
            expected_fee_bps=0.0,
            expected_slippage_bps=0.0,
            expected_total_cost_bps=0.0,
            min_trade_notional_usd=1.0,
            raw_notional_usd=100.0,
            capped_notional_usd=100.0,
            rejected_reason=None,
        )

    def can_open_under_max_trade_amount(self, *_args, **_kwargs):
        return True

    def exposure_block_reason(self, *_args, **_kwargs):
        return None

    def mark_trade(self, *_args, **_kwargs):
        return None

    def register_position(self, *_args, **_kwargs):
        return None

    def close_position(self, *_args, **_kwargs):
        return None


def _build_executor(cfg: dict) -> tuple[Executor, _FakePaper]:
    executor = Executor.__new__(Executor)
    executor.cfg = cfg
    executor.paper = _FakePaper()
    executor.risk = _FakeRisk()
    executor._daily_loss_close_all_day = None
    executor.last_execution_report = {}
    executor._consecutive_execution_failures = 0
    executor._execution_fail_pause_until = 0.0
    return executor, executor.paper


def test_executor_blocks_buy_on_bad_market_quality():
    executor, paper = _build_executor(
        {
            "risk": {"block_bad_market_quality": True},
            "trading_enabled": True,
        }
    )
    decision = {"symbol": "BTC-USD", "action": "BUY", "price": 100.0, "reason": "test"}
    market = {"symbol": "BTC-USD", "price": 100.0, "data_quality_status": "STALE"}
    ok = executor.handle_decision(decision, market=market)
    assert ok is False
    assert paper.buy_calls == 0


def test_executor_pauses_after_repeated_execution_failures():
    executor, paper = _build_executor(
        {
            "risk": {
                "block_bad_market_quality": False,
                "max_consecutive_execution_failures": 2,
                "execution_failure_pause_seconds": 60,
            },
            "trading_enabled": True,
        }
    )
    decision = {"symbol": "ETH-USD", "action": "BUY", "price": 100.0, "reason": "test"}
    market = {"symbol": "ETH-USD", "price": 100.0, "data_quality_status": "GOOD"}

    assert executor.handle_decision(decision, market=market) is False
    assert executor.handle_decision(decision, market=market) is False
    assert executor._execution_fail_pause_until > time.time()
    buy_calls_before = paper.buy_calls

    assert executor.handle_decision(decision, market=market) is False
    assert paper.buy_calls == buy_calls_before


def test_executor_blocks_buy_when_freshness_guard_active():
    executor, paper = _build_executor(
        {
            "risk": {
                "block_bad_market_quality": False,
            },
            "market_data": {
                "freshness_slo": {
                    "entry_block_on_degraded": True,
                    "entry_block_after_degraded_cycles": 1,
                }
            },
            "trading_enabled": True,
        }
    )
    executor.record_freshness_slo({"status": "DEGRADED"})
    decision = {"symbol": "BTC-USD", "action": "BUY", "price": 100.0, "reason": "test"}
    market = {"symbol": "BTC-USD", "price": 100.0, "data_quality_status": "GOOD"}

    assert executor.handle_decision(decision, market=market) is False
    assert paper.buy_calls == 0
    assert executor.last_execution_report.get("reason") == "freshness_slo_degraded"


def test_executor_read_execution_report_infers_legacy_schema():
    payload = Executor.read_execution_report({"status": "rejected", "reason": "timeout"})
    assert payload["schema_name"] == "execution_report"
    assert payload["schema_version"] == 1
    assert payload["_legacy_schema_inferred"] is True
