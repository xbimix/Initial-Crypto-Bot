from __future__ import annotations

import json

from data.replay_persistence import append_replay_event


def test_replay_persistence_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_DATA_DIR", str(tmp_path / "runtime"))
    append_replay_event("normalized_order_book", {"symbol": "BTC-USD"}, cfg={})
    path = tmp_path / "runtime" / "state" / "market_data_replay.jsonl"
    assert not path.exists()


def test_replay_persistence_writes_append_only_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_DATA_DIR", str(tmp_path / "runtime"))
    cfg = {"market_data": {"replay_log_enabled": True}}
    append_replay_event("normalized_order_book", {"symbol": "BTC-USD", "bids": 10}, cfg=cfg)
    append_replay_event("market_snapshot_change", {"symbol": "BTC-USD", "snapshot_version": 2}, cfg=cfg)

    path = tmp_path / "runtime" / "state" / "market_data_replay.jsonl"
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["event_type"] == "normalized_order_book"
    assert second["event_type"] == "market_snapshot_change"
    assert first["payload"]["symbol"] == "BTC-USD"
