from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from utils.state_paths import resolve_state_dir

SNAPSHOT_FILES = (
    "config.json",
    "paper_state.json",
    "strategy_state.json",
    "state.json",
    "trades.json",
)


def _state_dir_from_here() -> Path:
    default_state_dir = Path(__file__).resolve().parent.parent / "state"
    return resolve_state_dir(default_state_dir)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_reason(value: str) -> str:
    normalized = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "_"
        for ch in str(value).strip().lower()
    ).strip("_")
    return normalized or "snapshot"


def create_state_snapshot(
    *,
    reason: str,
    state_dir: str | Path | None = None,
    include_files: Iterable[str] = SNAPSHOT_FILES,
) -> Path:
    base = Path(state_dir) if state_dir is not None else _state_dir_from_here()
    snapshots_dir = base / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    ts = _utc_now().strftime("%Y%m%d-%H%M%S")
    snapshot_dir = snapshots_dir / f"{ts}_{_safe_reason(reason)}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    copied_files: list[str] = []
    missing_files: list[str] = []

    for file_name in include_files:
        src = base / file_name
        if not src.exists():
            missing_files.append(file_name)
            continue
        dst = snapshot_dir / file_name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied_files.append(file_name)

    manifest = {
        "generated_at_utc": _utc_now().isoformat(),
        "reason": reason,
        "state_dir": str(base),
        "snapshot_dir": str(snapshot_dir),
        "copied_files": copied_files,
        "missing_files": missing_files,
    }
    (snapshot_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return snapshot_dir


def ensure_daily_snapshot(
    *,
    reason: str,
    state_dir: str | Path | None = None,
) -> Path | None:
    base = Path(state_dir) if state_dir is not None else _state_dir_from_here()
    marker_path = base / ".last_daily_snapshot.json"
    day_utc = _utc_now().date().isoformat()

    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if isinstance(marker, dict) and marker.get("day_utc") == day_utc:
            return None
    except Exception:
        marker = {}

    snapshot_dir = create_state_snapshot(reason=reason, state_dir=base)
    marker_payload = {
        "day_utc": day_utc,
        "snapshot_dir": str(snapshot_dir),
        "updated_at_utc": _utc_now().isoformat(),
    }
    marker_path.write_text(json.dumps(marker_payload, indent=2), encoding="utf-8")
    return snapshot_dir
