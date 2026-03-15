from __future__ import annotations

from pathlib import Path

from utils.state_storage import JsonStateStorage


def test_json_state_storage_read_write_mutate(tmp_path: Path):
    storage = JsonStateStorage()
    path = tmp_path / "payload.json"

    storage.write(path, {"counter": 1})
    loaded = storage.read(path, strict=True)
    assert loaded["counter"] == 1

    updated = storage.mutate(
        path,
        lambda current: {"counter": int(current.get("counter", 0)) + 1},
        default={},
    )
    assert updated["counter"] == 2


def test_json_state_storage_transaction_lock(tmp_path: Path):
    storage = JsonStateStorage()
    lock_path = tmp_path / ".state_txn.lock"

    with storage.transaction(tmp_path):
        assert lock_path.exists()

    assert not lock_path.exists()
