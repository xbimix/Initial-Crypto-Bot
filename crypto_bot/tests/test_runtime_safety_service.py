from __future__ import annotations

from runtime.safety_service import RuntimeSafetyService
from trading.executor import Executor


class _FakeLogger:
    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None


class _FakeRisk:
    def __init__(self, daily_loss_state: dict):
        self._daily_loss_state = daily_loss_state

    def daily_loss_state(self):
        return dict(self._daily_loss_state)


class _FakePaper:
    def __init__(self):
        self.positions = {"BTC-USD": {"price": 100.0, "size": 1.0}}
        self.last_execution_report: dict = {}

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def get_position(self, symbol: str):
        return self.positions.get(symbol)

    def buy(self, *_args, **_kwargs):
        return False

    def sell(self, *_args, **_kwargs):
        return False


def test_daily_loss_breach_blocks_buy():
    service = RuntimeSafetyService(
        cfg={"risk": {}},
        risk_manager=_FakeRisk(
            {
                "buy_paused": True,
                "realized_usd": -120.0,
                "limit_usd": 100.0,
                "day": "2026-03-30",
            }
        ),
        logger=_FakeLogger(),
    )
    result = service.check_buy_allowed("BTC-USD", now_epoch=10.0)
    assert result.allowed is False
    assert result.blocked_reason == "daily_loss_buy_paused"


def test_pause_after_repeated_execution_failures_and_resume_after_expiry():
    service = RuntimeSafetyService(
        cfg={
            "risk": {
                "max_consecutive_execution_failures": 2,
                "execution_failure_pause_seconds": 60,
            }
        },
        risk_manager=_FakeRisk({"buy_paused": False, "limit_usd": 0.0, "realized_usd": 0.0}),
        logger=_FakeLogger(),
    )

    first = service.record_execution_failure(reason="timeout", now_epoch=100.0)
    assert first.blocked_reason is None

    second = service.record_execution_failure(reason="timeout", now_epoch=100.0)
    assert second.blocked_reason == "execution_failure_pause_activated"
    assert second.pause_until == 160.0

    blocked = service.check_buy_allowed("ETH-USD", now_epoch=120.0)
    assert blocked.allowed is False
    assert blocked.blocked_reason == "execution_failure_pause_active"

    resumed = service.check_buy_allowed("ETH-USD", now_epoch=161.0)
    assert resumed.allowed is True
    assert resumed.blocked_reason is None


def test_no_false_pause_when_threshold_not_reached():
    service = RuntimeSafetyService(
        cfg={
            "risk": {
                "max_consecutive_execution_failures": 3,
                "execution_failure_pause_seconds": 60,
            }
        },
        risk_manager=_FakeRisk({"buy_paused": False, "limit_usd": 0.0, "realized_usd": 0.0}),
        logger=_FakeLogger(),
    )

    service.record_execution_failure(reason="timeout", now_epoch=100.0)
    service.record_execution_failure(reason="timeout", now_epoch=101.0)
    result = service.check_buy_allowed("BTC-USD", now_epoch=102.0)
    assert result.allowed is True
    assert result.blocked_reason is None


def test_freshness_guard_blocks_buy_after_consecutive_degraded_cycles():
    service = RuntimeSafetyService(
        cfg={
            "risk": {},
            "market_data": {
                "freshness_slo": {
                    "entry_block_on_degraded": True,
                    "entry_block_after_degraded_cycles": 2,
                }
            },
        },
        risk_manager=_FakeRisk({"buy_paused": False, "limit_usd": 0.0, "realized_usd": 0.0}),
        logger=_FakeLogger(),
    )

    first = service.record_freshness_slo({"status": "DEGRADED"})
    assert first.allowed is True
    second = service.record_freshness_slo({"status": "DEGRADED"})
    assert second.allowed is False
    assert second.blocked_reason == "freshness_slo_degraded"

    blocked = service.check_buy_allowed("BTC-USD", now_epoch=200.0)
    assert blocked.allowed is False
    assert blocked.blocked_reason == "freshness_slo_degraded"


def test_freshness_guard_carries_structured_block_reason():
    service = RuntimeSafetyService(
        cfg={
            "risk": {},
            "market_data": {
                "freshness_slo": {
                    "entry_block_on_degraded": True,
                    "entry_block_after_degraded_cycles": 1,
                }
            },
        },
        risk_manager=_FakeRisk({"buy_paused": False, "limit_usd": 0.0, "realized_usd": 0.0}),
        logger=_FakeLogger(),
    )
    result = service.record_freshness_slo(
        {
            "status": "DEGRADED",
            "entry_block_reason": "decision_timeframe_starved",
        }
    )
    assert result.allowed is False
    assert result.counters.get("freshness_entry_block_reason") == "decision_timeframe_starved"
    blocked = service.check_buy_allowed("BTC-USD", now_epoch=250.0)
    assert blocked.counters.get("freshness_entry_block_reason") == "decision_timeframe_starved"


def test_freshness_guard_clears_after_status_recovers():
    service = RuntimeSafetyService(
        cfg={
            "risk": {},
            "market_data": {
                "freshness_slo": {
                    "entry_block_on_degraded": True,
                    "entry_block_after_degraded_cycles": 2,
                }
            },
        },
        risk_manager=_FakeRisk({"buy_paused": False, "limit_usd": 0.0, "realized_usd": 0.0}),
        logger=_FakeLogger(),
    )
    service.record_freshness_slo({"status": "DEGRADED"})
    service.record_freshness_slo({"status": "DEGRADED"})
    assert service.check_buy_allowed("ETH-USD", now_epoch=300.0).allowed is False

    recovered = service.record_freshness_slo({"status": "OK"})
    assert recovered.allowed is True
    allowed = service.check_buy_allowed("ETH-USD", now_epoch=301.0)
    assert allowed.allowed is True
    assert allowed.blocked_reason is None


def test_freshness_guard_blocks_entries_but_allows_risk_reducing_exits():
    daily_loss = {
        "buy_paused": True,
        "close_all": True,
        "day": "2026-04-05",
        "realized_usd": -250.0,
        "limit_usd": 100.0,
    }
    service = RuntimeSafetyService(
        cfg={
            "risk": {},
            "market_data": {
                "freshness_slo": {
                    "entry_block_on_degraded": True,
                    "entry_block_after_degraded_cycles": 1,
                }
            },
        },
        risk_manager=_FakeRisk(daily_loss),
        logger=_FakeLogger(),
    )
    service.record_freshness_slo({"status": "DEGRADED"})
    blocked = service.check_buy_allowed("BTC-USD", now_epoch=10.0)
    assert blocked.allowed is False
    assert blocked.blocked_reason == "freshness_slo_degraded"

    closed: list[tuple[str, float, str]] = []
    result = service.enforce_daily_loss_controls(
        open_symbols=["BTC-USD"],
        get_position=lambda symbol: {"size": 1.0} if symbol == "BTC-USD" else None,
        execute_sell=lambda symbol, price, reason: closed.append((symbol, price, reason)) or True,
        snapshot_fetcher=lambda _symbol, _cfg: {"price": 100.0},
    )
    assert result.counters["closed_positions"] == 1
    assert closed


def test_executor_daily_loss_controls_backward_compatible_bool_behavior():
    executor = Executor.__new__(Executor)
    executor.cfg = {"risk": {}}
    executor.paper = _FakePaper()
    executor.risk = _FakeRisk(
        {
            "buy_paused": True,
            "close_all": True,
            "day": "2026-03-30",
            "realized_usd": -150.0,
            "limit_usd": 100.0,
        }
    )
    executor.last_execution_report = {}
    executor._daily_loss_close_all_day = None
    executor._consecutive_execution_failures = 0
    executor._execution_fail_pause_until = 0.0

    calls: list[tuple[str, float, str]] = []

    def _sell(symbol: str, price: float, reason: str, trade_meta=None):
        calls.append((symbol, price, reason))
        return True

    executor._handle_sell = _sell  # type: ignore[method-assign]

    assert executor.enforce_daily_loss_controls() is True
    assert calls == [("BTC-USD", 100.0, "daily_loss_limit_close_all")]
    assert executor._daily_loss_close_all_day == "2026-03-30"

    assert executor.enforce_daily_loss_controls() is False
    assert len(calls) == 1
