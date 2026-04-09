from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.state_paths import resolve_state_file
from utils.state_io import file_lock

RUNTIME_EVENT_SCHEMA_NAME = "runtime_event"
RUNTIME_EVENT_SCHEMA_VERSION = 1


def runtime_events_path() -> Path:
    default_state_dir = Path(__file__).resolve().parent.parent / "state"
    return resolve_state_file(default_state_dir, "runtime_events.jsonl")


def _json_default(value: Any):
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def append_runtime_event(event_type: str, **fields: Any) -> None:
    path = runtime_events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    payload = {
        "schema_name": RUNTIME_EVENT_SCHEMA_NAME,
        "schema_version": RUNTIME_EVENT_SCHEMA_VERSION,
        "event_type": str(event_type),
        "time_utc": now.isoformat(),
        "day_utc": now.date().isoformat(),
        "pid": os.getpid(),
    }
    payload.update(fields)
    line = json.dumps(payload, default=_json_default, separators=(",", ":")) + "\n"
    with file_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


def read_runtime_events(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or runtime_events_path()
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in target.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if "schema_name" not in payload:
            payload["schema_name"] = RUNTIME_EVENT_SCHEMA_NAME
        if "schema_version" not in payload:
            payload["schema_version"] = RUNTIME_EVENT_SCHEMA_VERSION
            payload["_legacy_schema_inferred"] = True
        rows.append(payload)
    return rows
