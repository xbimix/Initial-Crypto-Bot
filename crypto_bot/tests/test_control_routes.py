from __future__ import annotations

from control import control_server


def test_control_start_and_kill_routes(monkeypatch):
    state = {"enabled": False, "emergency_stop": True, "symbols": []}

    def fake_update_config(mutator):
        nonlocal state
        state = mutator(dict(state))
        return state

    monkeypatch.setattr(control_server, "update_config", fake_update_config)
    client = control_server.app.test_client()

    start = client.post("/control", json={"action": "START"})
    assert start.status_code == 200
    payload = start.get_json()
    assert payload["enabled"] is True
    assert payload["emergency_stop"] is False

    kill = client.post("/kill", json={"reason": "test"})
    assert kill.status_code == 200
    payload = kill.get_json()
    assert payload["enabled"] is False
    assert payload["emergency_stop"] is True


def test_control_rejects_unknown_action():
    client = control_server.app.test_client()
    response = client.post("/control", json={"action": "INVALID"})
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
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["symbol"] == "ADA-USD"
    assert payload["enabled"] is False
    assert payload["symbol_buy_enabled"]["ADA-USD"] is False


def test_health_route():
    client = control_server.app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["service"] == "control"


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
