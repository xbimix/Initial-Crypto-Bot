from __future__ import annotations

from runtime.market_cycle_scheduler import resolve_sync_symbol_scope, sync_symbols_for_tick


def test_resolve_sync_symbol_scope_defaults_to_scan():
    assert resolve_sync_symbol_scope({}) == "scan"
    assert resolve_sync_symbol_scope({"market_data": {"sync_symbol_scope": "invalid"}}) == "scan"


def test_sync_symbols_for_tick_uses_cycle_scope():
    cfg = {"market_data": {"sync_symbol_scope": "cycle"}}
    selected = sync_symbols_for_tick(
        cfg=cfg,
        scan_symbols=["BTC-USD", "ETH-USD"],
        cycle_symbols=["ETH-USD"],
        open_symbols=["SOL-USD"],
    )
    assert selected == ["ETH-USD"]


def test_sync_symbols_for_tick_uses_scan_plus_open_scope():
    cfg = {"market_data": {"sync_symbol_scope": "scan_plus_open"}}
    selected = sync_symbols_for_tick(
        cfg=cfg,
        scan_symbols=["BTC-USD", "ETH-USD"],
        cycle_symbols=["ETH-USD"],
        open_symbols=["SOL-USD", "ETH-USD"],
    )
    assert selected == ["BTC-USD", "ETH-USD", "SOL-USD"]


def test_sync_symbols_for_tick_cycle_scope_appends_stale_catchup_symbols():
    cfg = {
        "market_data": {
            "sync_symbol_scope": "cycle",
            "sync_stale_catchup_enabled": True,
            "sync_stale_catchup_max_symbols": 1,
        }
    }
    selected = sync_symbols_for_tick(
        cfg=cfg,
        scan_symbols=["BTC-USD", "ETH-USD"],
        cycle_symbols=["ETH-USD"],
        open_symbols=["SOL-USD"],
        stale_symbols=["BTC-USD", "SOL-USD"],
    )
    assert selected == ["ETH-USD", "BTC-USD"]


def test_sync_symbols_for_tick_cycle_scope_can_disable_stale_catchup():
    cfg = {
        "market_data": {
            "sync_symbol_scope": "cycle",
            "sync_stale_catchup_enabled": False,
            "sync_stale_catchup_max_symbols": 2,
        }
    }
    selected = sync_symbols_for_tick(
        cfg=cfg,
        scan_symbols=["BTC-USD", "ETH-USD"],
        cycle_symbols=["ETH-USD"],
        open_symbols=["SOL-USD"],
        stale_symbols=["BTC-USD", "SOL-USD"],
    )
    assert selected == ["ETH-USD"]
