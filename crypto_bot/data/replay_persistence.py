from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping

from utils.state_paths import resolve_state_dir


def _runtime_state_dir() -> Path:
    return resolve_state_dir(Path(__file__).resolve().parent.parent / "state")


def replay_logging_enabled(cfg: dict | None) -> bool:
    market_cfg = (cfg or {}).get("market_data", {})
    if not isinstance(market_cfg, Mapping):
        return False
    return bool(market_cfg.get("replay_log_enabled", False))


def _replay_log_path(cfg: dict | None) -> Path:
    market_cfg = (cfg or {}).get("market_data", {})
    filename = "market_data_replay.jsonl"
    if isinstance(market_cfg, Mapping):
        raw = str(market_cfg.get("replay_log_filename") or "").strip()
        if raw:
            filename = raw
    return _runtime_state_dir() / filename


def append_replay_event(event_type: str, payload: Mapping[str, Any], cfg: dict | None = None) -> None:
    if not replay_logging_enabled(cfg):
        return
    path = _replay_log_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts_epoch": time.time(),
        "event_type": str(event_type or "").strip().lower() or "unknown",
        "payload": dict(payload),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=True))
        handle.write("\n")
