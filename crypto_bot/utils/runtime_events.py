from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.state_paths import resolve_state_file

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
        "event_type": str(event_type),
        "time_utc": now.isoformat(),
        "day_utc": now.date().isoformat(),
        "pid": os.getpid(),
    }
    payload.update(fields)
    line = json.dumps(payload, default=_json_default, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
