from __future__ import annotations

from pathlib import Path

import main as bot_main
from utils.state_io import write_json_file


def _seed_state_files(state_dir: Path):
    write_json_file(state_dir / "config.json", {"enabled": False, "symbols": []})
    write_json_file(state_dir / "paper_state.json", {"balance": 10000, "positions": {}})
    write_json_file(state_dir / "strategy_state.json", {})
    write_json_file(state_dir / "trades.json", [])


def test_startup_checks_ok(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    _seed_state_files(state_dir)

    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)
    monkeypatch.setattr(bot_main, "load_config", lambda: {"enabled": False})

    status = bot_main._run_startup_checks()
    assert status["ok"] is True
    names = {check["name"] for check in status["checks"]}
    assert "state_dir_exists" in names
    assert "state_dir_writable" in names
    assert "config_loadable" in names


def test_startup_checks_fail_when_config_unloadable(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    _seed_state_files(state_dir)

    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)

    def _fail():
        raise RuntimeError("config boom")

    monkeypatch.setattr(bot_main, "load_config", _fail)

    status = bot_main._run_startup_checks()
    assert status["ok"] is False
    failed = [item for item in status["checks"] if item["name"] == "config_loadable"]
    assert failed
    assert failed[0]["ok"] is False


def test_build_symbol_poll_intervals_prioritizes_open_and_top_symbols(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    _seed_state_files(state_dir)
    write_json_file(
        state_dir / "strategy_state.json",
        {
            "last_score": {
                "AAA-USD": 90,
                "BBB-USD": 70,
                "CCC-USD": 50,
                "DDD-USD": 10,
            },
            "last_volatility": {
                "AAA-USD": 0.02,
                "BBB-USD": 0.01,
            },
        },
    )

    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)
    cfg = {
        "symbols": ["AAA-USD", "BBB-USD", "CCC-USD", "DDD-USD", "EEE-USD"],
        "market_data": {
            "fast_poll_seconds": 20,
            "mid_poll_seconds": 90,
            "slow_poll_seconds": 240,
            "top_opportunity_count": 2,
            "mid_tier_count": 1,
        },
    }
    scan_symbols = cfg["symbols"]
    open_symbols = ["EEE-USD"]

    intervals = bot_main._build_symbol_poll_intervals(cfg, scan_symbols, open_symbols)

    assert intervals["EEE-USD"] == 20
    assert intervals["AAA-USD"] == 20
    assert intervals["BBB-USD"] == 20
    assert intervals["CCC-USD"] == 90
    assert intervals["DDD-USD"] == 240


def test_select_symbols_for_cycle_honors_due_and_max_per_cycle():
    symbols = ["AAA-USD", "BBB-USD", "CCC-USD", "DDD-USD"]
    now = 1_000.0
    interval_by_symbol = {
        "AAA-USD": 20,
        "BBB-USD": 20,
        "CCC-USD": 90,
        "DDD-USD": 240,
    }
    last_polled_at = {
        "AAA-USD": 970.0,   # due
        "BBB-USD": 990.0,   # not due
        "CCC-USD": 800.0,   # due
        "DDD-USD": 750.0,   # due
    }

    selected = bot_main._select_symbols_for_cycle(
        symbols=symbols,
        now_epoch=now,
        last_polled_at=last_polled_at,
        interval_by_symbol=interval_by_symbol,
        max_symbols_per_cycle=2,
    )

    # Fast tier due symbol should be selected first, then oldest due among remaining.
    assert selected == ["AAA-USD", "CCC-USD"]
    assert last_polled_at["AAA-USD"] == now
    assert last_polled_at["CCC-USD"] == now


def test_symbols_for_scan_prefers_active_tiers_and_keeps_open_symbols():
    class _Exec:
        @staticmethod
        def open_symbols():
            return ["DOGE-USD"]

    cfg = {
        "symbols": ["BTC-USD", "ETH-USD"],
        "market_data": {
            "active_tiers": ["tier1", "tier2"],
            "symbol_tiers": {
                "tier1": ["BTC-USD"],
                "tier2": ["SOL-USD"],
                "tier3": ["XRP-USD"],
            },
        },
    }

    symbols = bot_main._symbols_for_scan(cfg, _Exec())
    assert symbols == ["BTC-USD", "SOL-USD", "DOGE-USD"]
