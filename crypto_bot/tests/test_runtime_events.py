from __future__ import annotations

import importlib
import json
from pathlib import Path

from utils import runtime_events


def test_runtime_events_path_uses_runtime_state_root(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BOT_DATA_DIR", str(tmp_path / "runtime_root"))
    monkeypatch.delenv("REVBOT_STATE_DIR", raising=False)
    reloaded = importlib.reload(runtime_events)
    path = reloaded.runtime_events_path()
    assert "runtime_root" in str(path)
    assert path.name == "runtime_events.jsonl"


def test_append_runtime_event_writes_jsonl(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BOT_DATA_DIR", str(tmp_path / "runtime_root"))
    monkeypatch.delenv("REVBOT_STATE_DIR", raising=False)
    reloaded = importlib.reload(runtime_events)

    reloaded.append_runtime_event("unit_test", symbol="BTC-USD", score=88.5)
    path = reloaded.runtime_events_path()
    assert path.exists()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines
    payload = json.loads(lines[-1])
    assert payload["schema_name"] == "runtime_event"
    assert payload["schema_version"] == 1
    assert payload["event_type"] == "unit_test"
    assert payload["symbol"] == "BTC-USD"
    assert payload["score"] == 88.5


def test_read_runtime_events_infers_legacy_schema(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BOT_DATA_DIR", str(tmp_path / "runtime_root"))
    monkeypatch.delenv("REVBOT_STATE_DIR", raising=False)
    reloaded = importlib.reload(runtime_events)
    path = reloaded.runtime_events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"event_type":"legacy","symbol":"BTC-USD"}\n', encoding="utf-8")

    rows = reloaded.read_runtime_events(path)
    assert len(rows) == 1
    assert rows[0]["schema_name"] == "runtime_event"
    assert rows[0]["schema_version"] == 1
    assert rows[0]["_legacy_schema_inferred"] is True
