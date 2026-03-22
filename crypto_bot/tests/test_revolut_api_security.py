from __future__ import annotations

from pathlib import Path

import pytest

from api import revolut_api
from api import revolut_orders
from api import revolut_balances
from api import revolut_order_book
from api.revolut_secrets import load_api_key


def test_load_api_key_prefers_env_over_file(tmp_path: Path, monkeypatch):
    key_file = tmp_path / "api_key.txt"
    key_file.write_text("file-key", encoding="utf-8")

    monkeypatch.setenv("REVBOT_REVOLUT_API_KEY", "env-key")
    monkeypatch.setenv("REVBOT_REVOLUT_API_KEY_PATH", str(key_file))

    value, source = load_api_key(allow_missing=False)
    assert value == "env-key"
    assert source == "env:REVBOT_REVOLUT_API_KEY"


def test_load_api_key_file_fallback(tmp_path: Path, monkeypatch):
    key_file = tmp_path / "api_key.txt"
    key_file.write_text("file-only-key", encoding="utf-8")

    monkeypatch.delenv("REVBOT_REVOLUT_API_KEY", raising=False)
    monkeypatch.setenv("REVBOT_REVOLUT_API_KEY_PATH", str(key_file))

    value, source = load_api_key(allow_missing=False)
    assert value == "file-only-key"
    assert source == f"file:{key_file}"


def test_load_api_key_missing_env_path_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("REVBOT_REVOLUT_API_KEY", raising=False)
    monkeypatch.setenv("REVBOT_REVOLUT_API_KEY_PATH", "Z:/missing/revolut_api_key.txt")

    value, source = load_api_key(allow_missing=False)
    assert value
    assert source.startswith("file:")


def test_revolut_headers_include_user_agent_and_api_key(monkeypatch):
    monkeypatch.setenv("REVBOT_REVOLUT_API_KEY", "unit-test-key")
    monkeypatch.setattr(
        revolut_api,
        "_build_signed_headers",
        lambda **kwargs: {
            "Accept": "application/json",
            "User-Agent": "RevBot/1.0 (+local)",
            "X-Revx-API-Key": "unit-test-key",
            "X-Revx-Timestamp": "123",
            "X-Revx-Signature": "abc",
        },
    )
    headers = revolut_api._headers(auth_required=True)
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"] == "RevBot/1.0 (+local)"
    assert headers["X-Revx-API-Key"] == "unit-test-key"
    assert headers["X-Revx-Timestamp"] == "123"
    assert headers["X-Revx-Signature"] == "abc"


def test_revolut_headers_raise_without_api_key(monkeypatch):
    monkeypatch.delenv("REVBOT_REVOLUT_API_KEY", raising=False)
    monkeypatch.setenv("REVBOT_REVOLUT_API_KEY_PATH", "Z:/missing/revolut_api_key.txt")
    monkeypatch.setattr(
        revolut_api,
        "_build_signed_headers",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("missing auth")),
    )
    with pytest.raises(RuntimeError) as exc:
        revolut_api._headers(auth_required=True)
    assert "missing auth" in str(exc.value)


def test_balances_wrapper_uses_auth_flag(monkeypatch):
    captured = {}

    def fake_get(path, params=None, auth=False):
        captured["path"] = path
        captured["params"] = params
        captured["auth"] = auth
        return {"ok": True}

    monkeypatch.setattr(revolut_balances, "_get", fake_get)
    payload = revolut_balances.get_balances()
    assert payload["ok"] is True
    assert captured == {"path": "/balances", "params": None, "auth": True}


def test_orders_wrapper_uses_auth_flag(monkeypatch):
    captured = {}

    def fake_get(path, params=None, auth=False):
        captured["path"] = path
        captured["params"] = params
        captured["auth"] = auth
        return {"ok": True}

    monkeypatch.setattr(revolut_orders, "_get", fake_get)
    payload = revolut_orders.get_active_orders()
    assert payload["ok"] is True
    assert captured == {"path": "/orders", "params": None, "auth": True}


def test_public_retry_wait_is_capped_for_order_book(monkeypatch):
    class _Resp:
        def __init__(self, status, payload=None, headers=None):
            self.status_code = status
            self._payload = payload or {}
            self.headers = headers or {}

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                err = RuntimeError(f"HTTP {self.status_code}")
                err.response = self
                raise err

    responses = iter(
        [
            _Resp(429, headers={"Retry-After": "439"}),
            _Resp(200, payload={"data": {}}),
        ]
    )
    sleeps: list[float] = []

    def fake_get(*args, **kwargs):
        return next(responses)

    monkeypatch.setenv("REVBOT_PUBLIC_ORDERBOOK_RETRY_MAX_WAIT_SECONDS", "2")
    monkeypatch.setattr(revolut_api, "_throttle_public_request", lambda: None)
    monkeypatch.setattr(revolut_api._HTTP_SESSION, "get", fake_get)
    monkeypatch.setattr(revolut_api.time, "sleep", lambda s: sleeps.append(float(s)))

    payload = revolut_api._get("/public/order-book/BTC-USD", auth=False)
    assert payload == {"data": {}}
    assert sleeps
    assert sleeps[0] <= 2.0


def test_signed_message_concatenates_query_without_question_mark(monkeypatch):
    captured = {}

    class _FakeKey:
        def sign(self, message: bytes) -> bytes:
            captured["message"] = message.decode("utf-8")
            return b"sig"

    monkeypatch.setattr(revolut_api, "load_api_key", lambda allow_missing=True: ("k", "unit"))
    monkeypatch.setattr(revolut_api, "_load_signing_key", lambda: (_FakeKey(), "unit"))
    monkeypatch.setattr(revolut_api.time, "time", lambda: 1746007718.237)

    headers = revolut_api._build_signed_headers(
        method="GET",
        path="/market-data/candles/BTC-USD",
        params={"interval": 60, "since": 1, "until": 2},
    )
    assert headers["X-Revx-API-Key"] == "k"
    assert "?" not in captured["message"]
    assert "/api/1.0/market-data/candles/BTC-USDinterval=60&since=1&until=2" in captured["message"]


def test_order_book_prefers_authenticated_endpoint(monkeypatch):
    calls = []

    def fake_get(path, params=None, auth=False):
        calls.append((path, params, auth))
        return {"ok": True, "path": path, "auth": auth}

    monkeypatch.setattr(revolut_order_book, "_AUTH_ORDERBOOK_UNAVAILABLE_UNTIL_EPOCH", 0.0)
    monkeypatch.setattr(revolut_order_book, "_get", fake_get)
    payload = revolut_order_book.get_order_book("BTC-USD", limit=5)
    assert payload["ok"] is True
    assert calls[0][0] == "/order-book/BTC-USD"
    assert calls[0][2] is True
    assert calls[0][1] == {"limit": 5}


def test_order_book_falls_back_to_public_when_auth_unauthorized(monkeypatch):
    calls = []

    class _Resp:
        status_code = 401

    class _Err(RuntimeError):
        def __init__(self):
            super().__init__("401 Client Error: Unauthorized")
            self.response = _Resp()

    def fake_get(path, params=None, auth=False):
        calls.append((path, params, auth))
        if auth:
            raise _Err()
        return {"ok": True, "path": path, "auth": auth}

    monkeypatch.setattr(revolut_order_book, "_AUTH_ORDERBOOK_UNAVAILABLE_UNTIL_EPOCH", 0.0)
    monkeypatch.setattr(revolut_order_book, "_get", fake_get)
    payload = revolut_order_book.get_order_book("ETH-USD", limit=99)
    assert payload["ok"] is True
    assert payload["path"] == "/public/order-book/ETH-USD"
    assert payload["auth"] is False
    assert calls[0][0] == "/order-book/ETH-USD"
    assert calls[1][0] == "/public/order-book/ETH-USD"
    assert calls[1][1] == {"limit": 20}
