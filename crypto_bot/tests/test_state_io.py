from __future__ import annotations

import time
from pathlib import Path

import pytest

from utils import state_io


def test_read_json_file_returns_deepcopy_of_default(tmp_path: Path):
    payload = {"items": [1, 2]}
    loaded = state_io.read_json_file(tmp_path / "missing.json", default=payload)
    assert loaded == payload
    assert loaded is not payload
    assert loaded["items"] is not payload["items"]


def test_write_and_read_json_file_roundtrip(tmp_path: Path):
    path = tmp_path / "sample.json"
    expected = {"enabled": True, "risk": {"max_concurrent_trades": 5}}

    state_io.write_json_file(path, expected)
    actual = state_io.read_json_file(path, strict=True)

    assert actual == expected


def test_mutate_json_file_applies_update(tmp_path: Path):
    path = tmp_path / "config.json"
    state_io.write_json_file(path, {"counter": 1})

    updated = state_io.mutate_json_file(
        path,
        lambda current: {"counter": int(current.get("counter", 0)) + 1},
        default={},
    )

    assert updated["counter"] == 2
    assert state_io.read_json_file(path, strict=True)["counter"] == 2


def test_write_json_atomic_retries_replace_on_transient_permission_error(tmp_path: Path, monkeypatch):
    path = tmp_path / "state.json"
    real_replace = state_io.os.replace
    calls = {"count": 0}

    def _flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError("transient lock")
        return real_replace(src, dst)

    monkeypatch.setattr(state_io.os, "replace", _flaky_replace)
    state_io.write_json_atomic(path, {"ok": True})

    assert calls["count"] == 3
    assert state_io.read_json_file(path, strict=True)["ok"] is True


def test_file_lock_creates_and_removes_lock_file(tmp_path: Path):
    target = tmp_path / "state.json"
    lock_path = tmp_path / "state.json.lock"

    with state_io.file_lock(target):
        assert lock_path.exists()

    assert not lock_path.exists()


def test_state_transaction_lock_lifecycle(tmp_path: Path):
    lock_path = tmp_path / ".state_txn.lock"
    assert not lock_path.exists()

    with state_io.state_transaction_lock(tmp_path):
        assert lock_path.exists()

    assert not lock_path.exists()


def test_file_lock_timeout_when_prelocked(tmp_path: Path):
    target = tmp_path / "state.json"
    lock_path = tmp_path / "state.json.lock"
    lock_path.write_text("12345", encoding="utf-8")

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        with state_io.file_lock(
            target,
            timeout=0.05,
            poll_seconds=0.01,
            stale_seconds=0,
        ):
            pass

    assert (time.monotonic() - started) >= 0.04
