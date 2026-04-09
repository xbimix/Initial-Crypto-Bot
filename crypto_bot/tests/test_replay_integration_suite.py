from __future__ import annotations

import json
from pathlib import Path

from requests.exceptions import HTTPError

from paper import paper_broker as pb
from risk import risk_manager as rm
from runtime import periodic
from strategy import strategy_engine as se
from trading.executor import Executor
from utils.state_io import write_json_file


def _configure_state_paths(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    legacy_dir = tmp_path / "legacy_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    legacy_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(pb, "STATE_DIR", state_dir)
    monkeypatch.setattr(pb, "BALANCE_FILE", state_dir / "paper_state.json")
    monkeypatch.setattr(pb, "TRADES_FILE", state_dir / "trades.json")
    monkeypatch.setattr(pb, "LEGACY_BALANCE_FILE", legacy_dir / "paper_state.json")
    monkeypatch.setattr(pb, "LEGACY_TRADES_FILE", legacy_dir / "trades.json")

    monkeypatch.setattr(rm, "PAPER_STATE_FILE", state_dir / "paper_state.json")
    monkeypatch.setattr(rm, "TRADES_FILE", state_dir / "trades.json")
    monkeypatch.setattr(rm, "LEGACY_PAPER_STATE_FILE", legacy_dir / "paper_state.json")
    monkeypatch.setattr(rm, "LEGACY_TRADES_FILE", legacy_dir / "trades.json")

    monkeypatch.setattr(se, "STATE_DIR", state_dir)
    monkeypatch.setattr(se, "STRATEGY_STATE_FILE", state_dir / "strategy_state.json")
    monkeypatch.setattr(se, "PAPER_STATE_FILE", state_dir / "paper_state.json")

    write_json_file(state_dir / "paper_state.json", {"balance": 10000.0, "positions": {}})
    write_json_file(state_dir / "trades.json", [])
    write_json_file(state_dir / "strategy_state.json", {})
    return state_dir


def _base_cfg() -> dict:
    return {
        "starting_balance": 10000.0,
        "risk": {
            "cooldown_seconds": 0,
            "max_concurrent_trades": 10,
            "max_concurrent_trades_per_token": 2,
            "max_trade_amount_usd": 5000.0,
            "trade_amount_usd": 250.0,
            "max_portfolio_exposure_pct": 95.0,
            "max_exposure_per_token_pct": 50.0,
            "daily_loss_limit_usd": 1000.0,
            "daily_loss_auto_pause": True,
            "daily_loss_close_all": False,
            "block_bad_market_quality": True,
            "sizing_mode": "fixed_usd",
            "risk_percent": 1.0,
        },
        "paper_execution": {
            "enabled": True,
            "hard_reject_spread_bps": 1000.0,
            "soft_spread_bps": 150.0,
            "enable_timeouts": False,
            "base_slippage_bps": 0.0,
            "spread_slippage_weight": 0.0,
        },
    }


def _buy_decision(price: float = 100.0) -> dict:
    return {
        "symbol": "BTC-USD",
        "action": "BUY",
        "price": price,
        "reason": "replay_entry",
        "effective_route": "mean_reversion",
    }


def _sell_decision(price: float = 101.0) -> dict:
    return {
        "symbol": "BTC-USD",
        "action": "SELL",
        "price": price,
        "reason": "replay_exit",
        "effective_route": "mean_reversion",
    }


def _market(quality: str) -> dict:
    return {
        "symbol": "BTC-USD",
        "price": 100.0,
        "spread_bps": 12.0,
        "best_bid": 99.9,
        "best_ask": 100.1,
        "mid_price": 100.0,
        "atr_raw": 0.01,
        "momentum_norm": 0.2,
        "data_quality_status": quality,
    }


def test_replay_path_blocks_buy_on_stale_market_quality(monkeypatch, tmp_path: Path):
    state_dir = _configure_state_paths(tmp_path, monkeypatch)
    executor = Executor(_base_cfg())

    executed = executor.handle_decision(_buy_decision(100.0), _market("STALE"))
    assert executed is False

    trades = json.loads((state_dir / "trades.json").read_text(encoding="utf-8"))
    assert trades == []


def test_replay_path_allows_partial_quality_and_executes_roundtrip(monkeypatch, tmp_path: Path):
    state_dir = _configure_state_paths(tmp_path, monkeypatch)
    executor = Executor(_base_cfg())

    buy_ok = executor.handle_decision(_buy_decision(100.0), _market("PARTIAL"))
    assert buy_ok is True

    sell_ok = executor.handle_decision(_sell_decision(101.0), _market("PARTIAL"))
    assert sell_ok is True

    trades = json.loads((state_dir / "trades.json").read_text(encoding="utf-8"))
    assert len(trades) == 2
    assert trades[0]["side"] == "BUY"
    assert trades[1]["side"] == "SELL"


def test_replay_path_survives_api_409_sync_error_and_keeps_trading(monkeypatch, tmp_path: Path):
    _configure_state_paths(tmp_path, monkeypatch)
    executor = Executor(_base_cfg())

    logger_messages: list[str] = []

    class _Logger:
        @staticmethod
        def info(_msg):
            return None

        @staticmethod
        def warning(msg):
            logger_messages.append(str(msg))

    now = periodic.run_account_sync_if_due(
        now_epoch=500.0,
        last_run_at=0.0,
        interval_seconds=10.0,
        sync_fn=lambda: (_ for _ in ()).throw(HTTPError("409 Client Error: Conflict")),
        logger=_Logger(),
    )
    assert now == 500.0
    assert any("sync failed" in message.lower() for message in logger_messages)

    executed = executor.handle_decision(_buy_decision(100.0), _market("GOOD"))
    assert executed is True

