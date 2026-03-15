from __future__ import annotations

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
