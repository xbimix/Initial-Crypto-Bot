from __future__ import annotations

import sys
import types

import pytest

from control import control_server

AUTH_HEADERS = {
    "X-Revbot-Token": "test-token",
    "X-Revbot-Actor": "pytest",
}


@pytest.fixture(autouse=True)
def _reset_rate_buckets():
    control_server._rate_limit_buckets.clear()
    yield
    control_server._rate_limit_buckets.clear()


def test_mutating_endpoint_requires_auth(monkeypatch):
    monkeypatch.setenv("REVBOT_CONTROL_AUTH_TOKEN", "test-token")
    client = control_server.app.test_client()
    response = client.post("/control", json={"action": "START"})
    assert response.status_code == 401
    payload = response.get_json()
    assert payload["code"] == "unauthorized"


def test_mutating_endpoint_rejects_non_local(monkeypatch):
    monkeypatch.setenv("REVBOT_CONTROL_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(control_server, "ALLOW_NON_LOCAL_REQUESTS", False)
    client = control_server.app.test_client()

    response = client.post(
        "/control",
        json={"action": "START"},
        headers=AUTH_HEADERS,
        environ_overrides={"REMOTE_ADDR": "10.50.1.9"},
    )
    assert response.status_code == 403
    payload = response.get_json()
    assert payload["code"] == "non_local_forbidden"


def test_mutating_payload_size_limit(monkeypatch):
    monkeypatch.setenv("REVBOT_CONTROL_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(control_server, "MUTATING_PAYLOAD_MAX_BYTES", 16)
    client = control_server.app.test_client()

    response = client.post(
        "/config",
        data='{"x":"01234567890123456789"}',
        headers={
            **AUTH_HEADERS,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 413
    payload = response.get_json()
    assert payload["code"] == "payload_too_large"


def test_mutating_rate_limit(monkeypatch):
    monkeypatch.setenv("REVBOT_CONTROL_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(control_server, "RATE_LIMIT_MAX_REQUESTS", 1)
    monkeypatch.setattr(control_server, "RATE_LIMIT_WINDOW_SECONDS", 60)
    control_server._rate_limit_buckets.clear()

    state = {"enabled": False, "emergency_stop": False}

    def fake_update_config(mutator):
        nonlocal state
        state = mutator(dict(state))
        return state

    monkeypatch.setattr(control_server, "update_config", fake_update_config)

    client = control_server.app.test_client()
    first = client.post("/control", json={"action": "START"}, headers=AUTH_HEADERS)
    assert first.status_code == 200

    second = client.post("/control", json={"action": "STOP"}, headers=AUTH_HEADERS)
    assert second.status_code == 429
    payload = second.get_json()
    assert payload["code"] == "rate_limited"


def test_mutating_auth_must_be_configured(monkeypatch):
    monkeypatch.setattr(control_server, "_resolve_expected_auth_token", lambda: "")
    client = control_server.app.test_client()
    response = client.post("/control", json={"action": "START"}, headers=AUTH_HEADERS)
    assert response.status_code == 503
    payload = response.get_json()
    assert payload["code"] == "auth_not_configured"


def test_mutating_contract_blocks_deployed_without_explicit_flag(monkeypatch):
    monkeypatch.setenv("REVBOT_CONTROL_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(control_server, "DEPLOYMENT_MODE", True)
    monkeypatch.setattr(control_server, "STRICT_MUTATING_AUTH", True)
    monkeypatch.setattr(control_server, "ALLOW_DEPLOYED_MUTATIONS", False)
    monkeypatch.setattr(control_server, "ALLOW_DEPLOYED_LIVE_ARMING", False)
    client = control_server.app.test_client()
    response = client.post("/control", json={"action": "STOP"}, headers=AUTH_HEADERS)
    assert response.status_code == 503
    payload = response.get_json()
    assert payload["code"] == "mutating_contract_blocked"
    assert "deployed_mutations_not_enabled" in payload["details"]["failures"]


def test_live_arming_contract_blocks_start_in_live_mode(monkeypatch):
    monkeypatch.setenv("REVBOT_CONTROL_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(control_server, "DEPLOYMENT_MODE", True)
    monkeypatch.setattr(control_server, "STRICT_MUTATING_AUTH", True)
    monkeypatch.setattr(control_server, "ALLOW_DEPLOYED_MUTATIONS", True)
    monkeypatch.setattr(control_server, "ALLOW_DEPLOYED_LIVE_ARMING", False)
    monkeypatch.setattr(
        control_server,
        "load_config",
        lambda: {"execution_mode": "live", "enabled": False, "trading_enabled": False},
    )
    client = control_server.app.test_client()
    response = client.post("/control", json={"action": "START"}, headers=AUTH_HEADERS)
    assert response.status_code == 409
    payload = response.get_json()
    assert payload["code"] == "live_arming_contract_blocked"
    assert "deployed_live_arming_not_enabled" in payload["details"]["failures"]


def test_control_run_fails_fast_on_critical_startup_check(monkeypatch):
    monkeypatch.setattr(control_server, "STRICT_STARTUP", False)
    monkeypatch.setattr(
        control_server,
        "_refresh_startup_status",
        lambda: {
            "ok": False,
            "checks": [{"name": "arming_contract_mutating", "ok": False, "critical": True}],
        },
    )
    monkeypatch.setattr(control_server, "create_state_snapshot", lambda **kwargs: "snapshot")
    monkeypatch.setattr(control_server, "ensure_daily_snapshot", lambda **kwargs: None)
    monkeypatch.setattr(control_server, "append_runtime_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(control_server.app, "run", lambda **kwargs: (_ for _ in ()).throw(AssertionError("app.run should not be called")))

    with pytest.raises(RuntimeError, match="Control startup checks failed"):
        control_server.run()


def test_control_run_blocks_flask_dev_server_in_deployed_mode(monkeypatch):
    monkeypatch.setattr(control_server, "DEPLOYMENT_MODE", True)
    monkeypatch.setattr(control_server, "REQUIRE_PROD_CONTROL_SERVER_IN_DEPLOYED", True)
    monkeypatch.setattr(control_server, "CONTROL_SERVER_MODE", "flask")
    monkeypatch.setattr(
        control_server,
        "_refresh_startup_status",
        lambda: {"ok": True, "checks": []},
    )
    monkeypatch.setattr(control_server, "create_state_snapshot", lambda **kwargs: "snapshot")
    monkeypatch.setattr(control_server, "ensure_daily_snapshot", lambda **kwargs: None)
    monkeypatch.setattr(control_server, "append_runtime_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        control_server.app,
        "run",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("app.run should not be called")),
    )

    with pytest.raises(RuntimeError, match="Deployed mode requires production control server host"):
        control_server.run()


def test_control_run_uses_waitress_when_available(monkeypatch):
    calls = {"serve": 0}

    def _serve(app, host, port, threads):
        calls["serve"] += 1
        assert host == control_server.CONTROL_HOST
        assert port == control_server.CONTROL_PORT
        assert threads >= 1

    monkeypatch.setattr(control_server, "DEPLOYMENT_MODE", False)
    monkeypatch.setattr(control_server, "CONTROL_SERVER_MODE", "waitress")
    monkeypatch.setattr(
        control_server,
        "_refresh_startup_status",
        lambda: {"ok": True, "checks": []},
    )
    monkeypatch.setattr(control_server, "create_state_snapshot", lambda **kwargs: "snapshot")
    monkeypatch.setattr(control_server, "ensure_daily_snapshot", lambda **kwargs: None)
    monkeypatch.setattr(control_server, "append_runtime_event", lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "waitress", types.SimpleNamespace(serve=_serve))
    monkeypatch.setattr(
        control_server.app,
        "run",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("app.run should not be called")),
    )

    control_server.run()
    assert calls["serve"] == 1
