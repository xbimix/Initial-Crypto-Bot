from __future__ import annotations

import os
from pathlib import Path


def resolve_state_dir(default_dir: str | Path) -> Path:
    override = os.getenv("REVBOT_STATE_DIR", "").strip()
    if override:
        path = Path(override).expanduser()
    else:
        path = Path(default_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path
