from __future__ import annotations

import json
import time
from pathlib import Path

from utils import state_validator


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def test_validate_state_files_ok(tmp_path: Path):
    _write_json(
        tmp_path / "paper_state.json",
        {
            "balance": 1000.0,
            "positions": {
                "BTC-USD": {
                    "price": 100.0,
                    "size": 0.1,
                    "entry_time": time.time() - 60,
                }
            },
        },
    )
    _write_json(tmp_path / "strategy_state.json", {"entry_price": {"BTC-USD": 100.0}})
    _write_json(
        tmp_path / "trades.json",
        [
            {
                "trade_id": "t-1",
                "time": time.time() - 30,
                "symbol": "BTC-USD",
                "side": "BUY",
                "price": 100.0,
                "size": 0.1,
            }
        ],
    )

    report = state_validator.validate_state_files(tmp_path)
    assert report["ok"] is True
    assert report["errors"] == []


def test_validate_state_files_detects_invalid_values(tmp_path: Path):
    _write_json(
        tmp_path / "paper_state.json",
        {
            "balance": -1,
            "positions": {
                "BTC-USD": {
                    "price": -5,
                    "size": 0,
                    "entry_time": time.time() + 3600,
                }
            },
        },
    )
    _write_json(tmp_path / "strategy_state.json", {"entry_price": []})
    _write_json(
        tmp_path / "trades.json",
        [
            {
                "trade_id": "dup",
                "time": time.time() + 3600,
                "symbol": "",
                "side": "BUY",
                "price": -1,
                "size": 0,
            },
            {
                "trade_id": "dup",
                "time": time.time(),
                "symbol": "ETH-USD",
                "side": "MAYBE",
                "price": 1,
                "size": 1,
            },
        ],
    )

    report = state_validator.validate_state_files(tmp_path)
    assert report["ok"] is False
    assert any("duplicate trade_id" in err for err in report["errors"])
    assert any("paper_state.balance cannot be negative" in err for err in report["errors"])
