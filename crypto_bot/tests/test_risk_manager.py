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
