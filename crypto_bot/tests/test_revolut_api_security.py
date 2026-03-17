from __future__ import annotations

from pathlib import Path

import pytest

from api import revolut_api
from api import revolut_orders
from api import revolut_balances
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
