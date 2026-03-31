from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from risk import risk_manager as risk_module
from utils.state_io import write_json_file


def test_can_open_position_limits():
    rm = risk_module.RiskManager({"risk": {"max_concurrent_trades": 2}})
    assert rm.can_open_position(0) is True
    assert rm.can_open_position(1) is True
    assert rm.can_open_position(2) is False


def test_can_open_position_per_symbol_limits():
    rm = risk_module.RiskManager({"risk": {"max_concurrent_trades_per_token": 1}})
    assert rm.can_open_position_for_symbol(0) is True
    assert rm.can_open_position_for_symbol(1) is False


def test_can_trade_with_symbol_cooldown_override():
    rm = risk_module.RiskManager(
        {
            "risk": {
                "cooldown_seconds": 90,
                "symbol_cooldown_seconds": {"BTC-USD": 5},
            }
        }
    )
    rm.mark_trade("BTC-USD")
    assert rm.can_trade("BTC-USD") is False

    rm.last_trade_time["BTC-USD"] = time.time() - 6
    assert rm.can_trade("BTC-USD") is True


def test_can_trade_symbol_normalization_is_consistent():
    rm = risk_module.RiskManager({"risk": {"cooldown_seconds": 90}})
    rm.mark_trade("btc-usd")
    assert rm.can_trade("BTC-USD") is False


def test_exposure_block_reason_and_trade_amount_cap():
    rm = risk_module.RiskManager(
        {
            "starting_balance": 1000,
            "risk": {
                "max_trade_amount_usd": 600,
                "max_portfolio_exposure_pct": 50,
                "max_exposure_per_token_pct": 20,
            },
        }
    )
    assert rm.can_open_under_max_trade_amount(500, 120) is False
    reason = rm.exposure_block_reason(
        current_open_value_usd=300,
        current_symbol_value_usd=50,
        next_trade_cost_usd=250,
        equity_usd=1000,
    )
    assert "Portfolio exposure limit reached" in str(reason)


def test_trade_window_supports_wraparound():
    rm = risk_module.RiskManager(
        {
            "risk": {
                "trade_window_utc": {
                    "enabled": True,
                    "start_hour_utc": 22,
                    "end_hour_utc": 4,
                }
            }
        }
    )
    inside = datetime(2026, 3, 13, 23, 0, tzinfo=timezone.utc)
    outside = datetime(2026, 3, 13, 12, 0, tzinfo=timezone.utc)
    assert rm.is_within_trade_window(inside) is True
    assert rm.is_within_trade_window(outside) is False


def test_daily_loss_state_uses_sell_trades_only(tmp_path: Path, monkeypatch):
    trades_file = tmp_path / "trades.json"
    now = datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc).timestamp()
    day_start = datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc).timestamp()

    write_json_file(
        trades_file,
        [
            {"side": "BUY", "time": now - 1000, "pnl": 999},
            {"side": "SELL", "time": day_start - 10, "pnl": -100},
            {"side": "SELL", "time": now - 100, "pnl": -80},
            {"side": "SELL", "time": now - 50, "pnl": -50},
        ],
    )
    monkeypatch.setattr(risk_module, "TRADES_FILE", str(trades_file))

    rm = risk_module.RiskManager(
        {
            "risk": {
                "daily_loss_limit_usd": 100,
                "daily_loss_auto_pause": True,
                "daily_loss_close_all": False,
            }
        }
    )
    state = rm.daily_loss_state(now=now)
    assert state["realized_usd"] == -130
    assert state["breached"] is True
    assert state["buy_paused"] is True
    assert state["close_all"] is False


def test_position_size_uses_stop_distance_when_available():
    rm = risk_module.RiskManager(
        {
            "starting_balance": 10000,
            "risk": {
                "risk_percent": 0.02,
                "trade_amount_usd": 1000,
                "stop_atr_mult_default": 1.5,
            },
        }
    )
    size_no_stop = rm.position_size(10000, 100.0, volatility=0.01)
    size_with_stop = rm.position_size(
        10000,
        100.0,
        volatility=0.01,
        stop_price=97.0,
        expected_fee_bps=10,
        expected_slippage_bps=15,
    )
    assert size_with_stop > 0
    assert size_with_stop <= size_no_stop


def test_position_sizing_returns_detailed_contract():
    rm = risk_module.RiskManager(
        {
            "starting_balance": 10000,
            "risk": {
                "sizing_mode": "stop_distance",
                "risk_percent": 0.02,
                "min_trade_notional_usd": 5.0,
            },
        }
    )
    result = rm.position_sizing(
        10000,
        100.0,
        stop_price=97.0,
        expected_fee_bps=10.0,
        expected_slippage_bps=15.0,
    )
    assert result.capped_size > 0
    assert result.raw_size >= result.capped_size
    assert result.stop_distance == 3.0
    assert result.expected_total_cost_bps == 25.0
    assert result.rejected_reason is None


def test_position_sizing_rejects_missing_stop_in_stop_distance_mode():
    rm = risk_module.RiskManager(
        {
            "starting_balance": 10000,
            "risk": {
                "sizing_mode": "stop_distance",
                "risk_percent": 0.02,
            },
        }
    )
    result = rm.position_sizing(10000, 100.0, stop_price=None)
    assert result.capped_size == 0.0
    assert result.rejected_reason == "missing_or_invalid_stop"


def test_position_sizing_applies_notional_caps():
    rm = risk_module.RiskManager(
        {
            "starting_balance": 10000,
            "risk": {
                "sizing_mode": "risk_percent",
                "risk_percent": 0.10,
                "max_notional_usd": 250.0,
                "min_trade_notional_usd": 10.0,
            },
        }
    )
    result = rm.position_sizing(10000, 100.0, stop_price=90.0)
    assert result.raw_notional_usd >= result.capped_notional_usd
    assert result.capped_notional_usd <= 250.0
    assert result.capped_size <= 2.5


def test_position_sizing_accounts_for_fee_and_slippage_assumptions():
    rm = risk_module.RiskManager(
        {
            "starting_balance": 10000,
            "risk": {
                "sizing_mode": "stop_distance",
                "risk_percent": 0.50,
                "min_trade_notional_usd": 1.0,
            },
        }
    )
    no_cost = rm.position_sizing(10000, 100.0, stop_price=99.0, expected_fee_bps=0.0, expected_slippage_bps=0.0)
    high_cost = rm.position_sizing(10000, 100.0, stop_price=99.0, expected_fee_bps=20000.0, expected_slippage_bps=20000.0)
    assert high_cost.capped_size < no_cost.capped_size


def test_position_size_blocks_on_hard_spread_or_thin_liquidity():
    rm = risk_module.RiskManager(
        {
            "starting_balance": 10000,
            "risk": {
                "risk_percent": 0.02,
                "trade_amount_usd": 1000,
                "liquidity_hard_spread_bps": 120,
                "liquidity_score_floor": 0.2,
            },
        }
    )
    blocked_spread = rm.position_size(10000, 100.0, spread_bps=180)
    blocked_liq = rm.position_size(10000, 100.0, spread_bps=10, liquidity_score=0.05)
    assert blocked_spread == 0.0
    assert blocked_liq == 0.0


def test_position_size_remains_backward_compatible_scalar():
    rm = risk_module.RiskManager(
        {
            "starting_balance": 10000,
            "risk": {
                "trade_amount_usd": 500,
                "risk_percent": 0.02,
            },
        }
    )
    size = rm.position_size(10000, 100.0, stop_price=95.0)
    assert isinstance(size, float)
    assert size > 0.0


def test_daily_loss_state_falls_back_to_legacy_trades_file(tmp_path: Path, monkeypatch):
    runtime_trades = tmp_path / "runtime" / "trades.json"
    legacy_trades = tmp_path / "legacy" / "trades.json"
    now = datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc).timestamp()
    write_json_file(
        legacy_trades,
        [
            {"side": "SELL", "time": now - 20, "pnl": -12.0},
            {"side": "SELL", "time": now - 10, "pnl": -8.0},
        ],
    )

    monkeypatch.setattr(risk_module, "TRADES_FILE", runtime_trades)
    monkeypatch.setattr(risk_module, "LEGACY_TRADES_FILE", legacy_trades)

    rm = risk_module.RiskManager({"risk": {"daily_loss_limit_usd": 50}})
    state = rm.daily_loss_state(now=now)
    assert state["realized_usd"] == -20.0
