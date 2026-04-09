from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from control import control_server

AUTH_HEADERS = {
    "X-Revbot-Token": "test-token",
    "X-Revbot-Actor": "pytest",
}


@pytest.fixture(autouse=True)
def _set_control_auth_token(monkeypatch):
    monkeypatch.setenv("REVBOT_CONTROL_AUTH_TOKEN", "test-token")


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_control_start_and_kill_routes(monkeypatch):
    state = {"enabled": False, "trading_enabled": False, "emergency_stop": True, "symbols": []}

    def fake_update_config(mutator):
        nonlocal state
        state = mutator(dict(state))
        return state

    monkeypatch.setattr(control_server, "update_config", fake_update_config)
    client = control_server.app.test_client()

    start = client.post("/control", json={"action": "START"}, headers=AUTH_HEADERS)
    assert start.status_code == 200
    payload = start.get_json()
    assert payload["enabled"] is True
    assert payload["trading_enabled"] is True
    assert payload["emergency_stop"] is False

    kill = client.post("/kill", json={"reason": "test"}, headers=AUTH_HEADERS)
    assert kill.status_code == 200
    payload = kill.get_json()
    assert payload["enabled"] is False
    assert payload["trading_enabled"] is False
    assert payload["emergency_stop"] is True


def test_control_stop_disarms_trading_keeps_process_online(monkeypatch):
    state = {"enabled": True, "trading_enabled": True, "emergency_stop": False, "symbols": []}

    def fake_update_config(mutator):
        nonlocal state
        state = mutator(dict(state))
        return state

    monkeypatch.setattr(control_server, "update_config", fake_update_config)
    client = control_server.app.test_client()

    response = client.post("/control", json={"action": "STOP"}, headers=AUTH_HEADERS)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["enabled"] is True
    assert payload["trading_enabled"] is False
    assert payload["emergency_stop"] is False


def test_control_rejects_unknown_action():
    client = control_server.app.test_client()
    response = client.post("/control", json={"action": "INVALID"}, headers=AUTH_HEADERS)
    assert response.status_code == 400
    assert "Unknown action" in response.get_json()["error"]


def test_symbols_route_updates_side_specific_map(monkeypatch):
    state = {"symbols": [], "symbol_buy_enabled": {}, "symbol_sell_enabled": {}}

    def fake_update_config(mutator):
        nonlocal state
        state = mutator(dict(state))
        return state

    monkeypatch.setattr(control_server, "update_config", fake_update_config)
    client = control_server.app.test_client()

    response = client.post(
        "/symbols",
        json={"symbol": "ada-usd", "side": "buy", "enabled": False},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["symbol"] == "ADA-USD"
    assert payload["enabled"] is False
    assert payload["symbol_buy_enabled"]["ADA-USD"] is False


def test_universe_track_route_add_and_remove(monkeypatch):
    state = {"symbols": ["BTC-USD"], "symbol_buy_enabled": {}, "symbol_sell_enabled": {}}

    def fake_update_config(mutator):
        nonlocal state
        state = mutator(dict(state))
        return state

    monkeypatch.setattr(control_server, "update_config", fake_update_config)
    monkeypatch.setattr(control_server, "_has_open_position", lambda _symbol: False)
    client = control_server.app.test_client()

    add = client.post(
        "/universe-track",
        json={"symbol": "eth-usd", "tracked": True},
        headers=AUTH_HEADERS,
    )
    assert add.status_code == 200
    add_payload = add.get_json()
    assert "ETH-USD" in add_payload["symbols"]
    assert add_payload["symbol_buy_enabled"]["ETH-USD"] is True

    remove = client.post(
        "/universe-track",
        json={"symbol": "eth-usd", "tracked": False},
        headers=AUTH_HEADERS,
    )
    assert remove.status_code == 200
    remove_payload = remove.get_json()
    assert "ETH-USD" not in remove_payload["symbols"]
    assert "ETH-USD" not in remove_payload["symbol_buy_enabled"]
    assert "ETH-USD" not in remove_payload["symbol_sell_enabled"]


def test_universe_track_route_blocks_remove_when_open_position(monkeypatch):
    state = {"symbols": ["ETH-USD"], "symbol_buy_enabled": {"ETH-USD": True}, "symbol_sell_enabled": {"ETH-USD": True}}
    update_calls = {"count": 0}

    def fake_update_config(mutator):
        nonlocal state
        update_calls["count"] += 1
        state = mutator(dict(state))
        return state

    monkeypatch.setattr(control_server, "update_config", fake_update_config)
    monkeypatch.setattr(control_server, "_has_open_position", lambda symbol: symbol == "ETH-USD")
    client = control_server.app.test_client()

    remove = client.post(
        "/universe-track",
        json={"symbol": "eth-usd", "tracked": False},
        headers=AUTH_HEADERS,
    )
    assert remove.status_code == 409
    payload = remove.get_json()
    assert payload["code"] == "open_position_exists"
    assert update_calls["count"] == 0


def test_token_regime_route_updates_single_symbol(monkeypatch):
    state = {"symbols": ["BTC-USD"], "token_regimes": {"BTC-USD": "AUTO"}}

    def fake_update_config(mutator):
        nonlocal state
        state = mutator(dict(state))
        return state

    monkeypatch.setattr(control_server, "update_config", fake_update_config)
    client = control_server.app.test_client()

    response = client.post(
        "/token-regime",
        json={"symbol": "eth-usd", "regime": "TREND_PULLBACK"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["symbol"] == "ETH-USD"
    assert payload["configured_regime"] == "TREND_PULLBACK"
    assert payload["token_regimes"]["ETH-USD"] == "TREND_PULLBACK"
    assert payload["token_regimes"]["BTC-USD"] == "AUTO"


def test_token_regime_route_rejects_invalid_value():
    client = control_server.app.test_client()
    response = client.post(
        "/token-regime",
        json={"symbol": "BTC-USD", "regime": "INVALID"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert "regime must be one of" in payload["error"]


def test_health_route():
    client = control_server.app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["service"] == "control"


def test_revolut_account_route_reads_snapshot(monkeypatch):
    monkeypatch.setattr(
        control_server,
        "read_account_snapshot",
        lambda default=None: {"sync_status": "ok", "asset_count": 2, "assets": []},
    )
    client = control_server.app.test_client()
    response = client.get("/revolut-account")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["sync_status"] == "ok"
    assert payload["asset_count"] == 2


def test_revolut_universe_route_returns_snapshot(monkeypatch):
    monkeypatch.setattr(control_server, "load_config", lambda: {"symbols": ["BTC-USD"]})
    monkeypatch.setattr(
        control_server,
        "get_universe_snapshot",
        lambda cfg, force_refresh=False: {
            "sync_status": "ok",
            "summary": {"total_symbols": 1, "eligible_count": 1, "tracked_count": 1, "ineligible_count": 0, "top_score": 72},
            "rows": [{"symbol": "BTC-USD", "eligible": True, "tracked": True}],
        },
    )

    client = control_server.app.test_client()
    response = client.get("/revolut-universe")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["total_symbols"] == 1
    assert payload["rows"][0]["symbol"] == "BTC-USD"


def test_ready_route_ok(monkeypatch):
    client = control_server.app.test_client()
    monkeypatch.setattr(
        control_server,
        "_refresh_startup_status",
        lambda: {"ok": True, "checkedAt": "2026-03-13T00:00:00+00:00", "checks": []},
    )
    response = client.get("/ready")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"


def test_ready_route_not_ready(monkeypatch):
    client = control_server.app.test_client()
    monkeypatch.setattr(
        control_server,
        "_refresh_startup_status",
        lambda: {"ok": False, "checkedAt": "2026-03-13T00:00:00+00:00", "checks": []},
    )
    response = client.get("/ready")
    assert response.status_code == 503
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["code"] == "not_ready"


def test_manual_sell_action_id_is_idempotent(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    paper_path = state_dir / "paper_state.json"
    strategy_path = state_dir / "strategy_state.json"
    trades_path = state_dir / "trades.json"
    cache_path = state_dir / "manual_action_cache.json"

    _write_json(
        paper_path,
        {
            "balance": 1000.0,
            "positions": {
                "BTC-USD": {
                    "price": 100.0,
                    "size": 1.0,
                    "entry_time": time.time() - 60,
                }
            },
        },
    )
    _write_json(strategy_path, {})
    _write_json(trades_path, [])
    _write_json(cache_path, {})

    monkeypatch.setattr(control_server, "STATE_DIR", state_dir)
    monkeypatch.setattr(control_server, "PAPER_STATE_PATH", paper_path)
    monkeypatch.setattr(control_server, "STRATEGY_STATE_PATH", strategy_path)
    monkeypatch.setattr(control_server, "TRADES_PATH", trades_path)
    monkeypatch.setattr(control_server, "MANUAL_ACTION_CACHE_PATH", cache_path)
    monkeypatch.setattr(control_server, "_read_latest_snapshot_price", lambda _symbol: 101.0)

    client = control_server.app.test_client()
    first = client.post(
        "/manual-sell",
        json={"symbol": "BTC-USD", "actionId": "abc-1"},
        headers=AUTH_HEADERS,
    )
    assert first.status_code == 200
    second = client.post(
        "/manual-sell",
        json={"symbol": "BTC-USD", "actionId": "abc-1"},
        headers=AUTH_HEADERS,
    )
    assert second.status_code == 200
    payload_second = second.get_json()
    assert payload_second["idempotent_replay"] is True

    trades = json.loads(trades_path.read_text(encoding="utf-8"))
    assert len(trades) == 1


def test_close_all_action_id_is_idempotent(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    paper_path = state_dir / "paper_state.json"
    strategy_path = state_dir / "strategy_state.json"
    trades_path = state_dir / "trades.json"
    cache_path = state_dir / "manual_action_cache.json"

    _write_json(
        paper_path,
        {
            "balance": 1000.0,
            "positions": {
                "BTC-USD": {"price": 100.0, "size": 1.0, "entry_time": time.time() - 60},
                "ETH-USD": {"price": 50.0, "size": 2.0, "entry_time": time.time() - 60},
            },
        },
    )
    _write_json(strategy_path, {})
    _write_json(trades_path, [])
    _write_json(cache_path, {})

    monkeypatch.setattr(control_server, "STATE_DIR", state_dir)
    monkeypatch.setattr(control_server, "PAPER_STATE_PATH", paper_path)
    monkeypatch.setattr(control_server, "STRATEGY_STATE_PATH", strategy_path)
    monkeypatch.setattr(control_server, "TRADES_PATH", trades_path)
    monkeypatch.setattr(control_server, "MANUAL_ACTION_CACHE_PATH", cache_path)
    monkeypatch.setattr(control_server, "_read_latest_snapshot_price", lambda _symbol: 110.0)

    client = control_server.app.test_client()
    first = client.post(
        "/close-all",
        json={"reason": "test", "actionId": "xyz-1"},
        headers=AUTH_HEADERS,
    )
    assert first.status_code == 200
    second = client.post(
        "/close-all",
        json={"reason": "test", "actionId": "xyz-1"},
        headers=AUTH_HEADERS,
    )
    assert second.status_code == 200
    payload_second = second.get_json()
    assert payload_second["idempotent_replay"] is True

    trades = json.loads(trades_path.read_text(encoding="utf-8"))
    assert len(trades) == 2
