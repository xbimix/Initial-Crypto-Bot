from __future__ import annotations

from pathlib import Path

from paper import paper_broker as pb
from utils.state_io import read_json_file, write_json_file


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
    return state_dir


def test_paper_buy_rejects_on_hard_spread(monkeypatch, tmp_path: Path):
    _configure_state_paths(tmp_path, monkeypatch)
    broker = pb.PaperBroker(
        10000,
        cfg={
            "paper_execution": {
                "enabled": True,
                "hard_reject_spread_bps": 100,
            }
        },
    )

    ok = broker.buy(
        "BTC-USD",
        100.0,
        1.0,
        "test_buy",
        trade_meta={"spread_bps": 180.0, "data_quality_status": "GOOD"},
    )
    assert ok is False
    assert broker.last_execution_report["status"] == "rejected"
    assert broker.last_execution_report["reason"] == "spread_too_wide"
    assert broker.last_execution_report["schema_name"] == "execution_report"
    assert broker.last_execution_report["schema_version"] == 1


def test_paper_buy_partial_fill_records_diagnostics(monkeypatch, tmp_path: Path):
    state_dir = _configure_state_paths(tmp_path, monkeypatch)
    broker = pb.PaperBroker(
        10000,
        cfg={
            "paper_execution": {
                "enabled": True,
                "liquidity_reference_usd": 100.0,
                "partial_fill_notional_pressure": 0.4,
                "partial_fill_slope": 0.7,
                "soft_spread_bps": 20.0,
                "hard_reject_spread_bps": 500.0,
                "enable_timeouts": False,
            }
        },
    )

    requested_size = 20.0
    ok = broker.buy(
        "ETH-USD",
        50.0,
        requested_size,
        "test_partial_buy",
        trade_meta={"spread_bps": 35.0, "data_quality_status": "GOOD", "book_imbalance": 0.8},
    )
    assert ok is True
    pos = broker.get_position("ETH-USD")
    assert pos is not None
    assert 0 < float(pos["size"]) < requested_size
    assert broker.last_execution_report["status"] in {"partial", "filled"}
    assert float(broker.last_execution_report.get("fee_usd", 0.0)) >= 0.0

    trades = read_json_file(state_dir / "trades.json", strict=True)
    assert isinstance(trades, list) and trades
    last_trade = trades[-1]
    assert last_trade["side"] == "BUY"
    assert last_trade["schema_name"] == "trade_record"
    assert last_trade["schema_version"] == 1
    assert "execution_status" in last_trade
    assert "slippage_bps" in last_trade
    assert "latency_ms" in last_trade


def test_paper_sell_partial_keeps_remaining_position(monkeypatch, tmp_path: Path):
    _configure_state_paths(tmp_path, monkeypatch)
    broker = pb.PaperBroker(
        10000,
        cfg={
            "paper_execution": {
                "enabled": True,
                "liquidity_reference_usd": 100.0,
                "partial_fill_notional_pressure": 0.4,
                "partial_fill_slope": 0.7,
                "hard_reject_spread_bps": 500.0,
                "enable_timeouts": False,
            }
        },
    )
    broker.buy(
        "SOL-USD",
        100.0,
        10.0,
        "enter",
        trade_meta={"spread_bps": 20.0, "data_quality_status": "GOOD"},
    )
    before = broker.get_position("SOL-USD")
    assert before is not None
    before_size = float(before["size"])

    ok = broker.sell(
        "SOL-USD",
        101.0,
        "exit_partial",
        trade_meta={"spread_bps": 20.0, "data_quality_status": "GOOD"},
    )
    assert ok is True
    report = broker.last_execution_report
    assert report["status"] in {"partial", "filled"}
    if not bool(report.get("position_closed", True)):
        after = broker.get_position("SOL-USD")
        assert after is not None
        assert 0 < float(after["size"]) < before_size


def test_paper_broker_reads_legacy_state_when_runtime_empty(monkeypatch, tmp_path: Path):
    state_dir = tmp_path / "state"
    legacy_dir = tmp_path / "legacy_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    legacy_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(pb, "STATE_DIR", state_dir)
    monkeypatch.setattr(pb, "BALANCE_FILE", state_dir / "paper_state.json")
    monkeypatch.setattr(pb, "TRADES_FILE", state_dir / "trades.json")
    monkeypatch.setattr(pb, "LEGACY_BALANCE_FILE", legacy_dir / "paper_state.json")
    monkeypatch.setattr(pb, "LEGACY_TRADES_FILE", legacy_dir / "trades.json")

    (legacy_dir / "paper_state.json").write_text(
        '{"balance":9000.0,"positions":{"BTC-USD":{"price":100.0,"size":1.0}}}',
        encoding="utf-8",
    )
    (legacy_dir / "trades.json").write_text("[]", encoding="utf-8")

    broker = pb.PaperBroker(10000, cfg={})
    assert broker.get_balance() == 9000.0
    assert broker.has_position("BTC-USD") is True


def test_paper_execution_applies_fees_and_net_pnl(monkeypatch, tmp_path: Path):
    state_dir = _configure_state_paths(tmp_path, monkeypatch)
    broker = pb.PaperBroker(
        10000,
        cfg={
            "paper_execution": {
                "enabled": True,
                "taker_fee_bps": 20.0,
                "base_slippage_bps": 0.0,
                "spread_slippage_weight": 0.0,
                "participation_penalty_bps": 0.0,
                "imbalance_penalty_bps": 0.0,
                "momentum_penalty_bps": 0.0,
                "microprice_weight": 0.0,
                "enable_timeouts": False,
                "hard_reject_spread_bps": 500.0,
            }
        },
    )

    assert broker.buy("BTC-USD", 100.0, 1.0, "fee_test", trade_meta={"spread_bps": 0.0, "data_quality_status": "GOOD"})
    assert broker.sell("BTC-USD", 100.0, "fee_test_exit", trade_meta={"spread_bps": 0.0, "data_quality_status": "GOOD"})

    trades = read_json_file(state_dir / "trades.json", strict=True)
    buy_trade = next(row for row in trades if row.get("side") == "BUY")
    sell_trade = next(row for row in trades if row.get("side") == "SELL")
    assert float(buy_trade.get("fee_usd", 0.0)) > 0.0
    assert float(sell_trade.get("fee_usd", 0.0)) > 0.0
    assert float(sell_trade.get("pnl", 0.0)) < 0.0


def test_paper_execution_slippage_is_directional(monkeypatch, tmp_path: Path):
    _configure_state_paths(tmp_path, monkeypatch)
    broker = pb.PaperBroker(
        10000,
        cfg={
            "paper_execution": {
                "enabled": True,
                "base_slippage_bps": 5.0,
                "spread_slippage_weight": 0.2,
                "hard_reject_spread_bps": 500.0,
                "enable_timeouts": False,
            }
        },
    )
    buy_ok = broker.buy("ETH-USD", 100.0, 0.5, "slippage_buy", trade_meta={"spread_bps": 25.0, "data_quality_status": "GOOD"})
    assert buy_ok is True
    buy_report = broker.last_execution_report
    assert float(buy_report.get("fill_price", 0.0)) > 100.0

    sell_ok = broker.sell("ETH-USD", 100.0, "slippage_sell", trade_meta={"spread_bps": 25.0, "data_quality_status": "GOOD"})
    assert sell_ok is True
    sell_report = broker.last_execution_report
    assert float(sell_report.get("fill_price", 0.0)) < 100.0


def test_paper_execution_can_timeout(monkeypatch, tmp_path: Path):
    _configure_state_paths(tmp_path, monkeypatch)
    broker = pb.PaperBroker(
        10000,
        cfg={
            "paper_execution": {
                "enabled": True,
                "timeout_ms": 50,
                "enable_timeouts": True,
                "hard_reject_spread_bps": 500.0,
            }
        },
    )
    ok = broker.buy(
        "SOL-USD",
        20.0,
        1.0,
        "timeout_test",
        trade_meta={"spread_bps": 80.0, "data_quality_status": "GOOD"},
    )
    assert ok is False
    assert broker.last_execution_report.get("status") == "timeout"


def test_paper_broker_read_trades_infers_legacy_schema(monkeypatch, tmp_path: Path):
    state_dir = _configure_state_paths(tmp_path, monkeypatch)
    legacy_rows = [
        {"symbol": "BTC-USD", "side": "BUY", "price": 100.0, "size": 1.0},
    ]
    write_json_file(state_dir / "trades.json", legacy_rows)

    broker = pb.PaperBroker(10000, cfg={})
    rows = broker.read_trades()
    assert len(rows) == 1
    assert rows[0]["schema_name"] == "trade_record"
    assert rows[0]["schema_version"] == 1
    assert rows[0]["_legacy_schema_inferred"] is True
