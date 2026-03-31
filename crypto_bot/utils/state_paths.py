from __future__ import annotations

import os
import shutil
from pathlib import Path


BOT_DATA_DIR_ENV = "BOT_DATA_DIR"
LEGACY_STATE_DIR_ENV = "REVBOT_STATE_DIR"
DEFAULT_RUNTIME_DATA_DIR = ".runtime"
DEFAULT_STATE_SUBDIR = "state"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_runtime_data_dir(default_dir: str | Path | None = None) -> Path:
    override = os.getenv(BOT_DATA_DIR_ENV, "").strip()
    if override:
        path = Path(override).expanduser()
    elif default_dir is not None:
        path = Path(default_dir)
    else:
        path = project_root() / DEFAULT_RUNTIME_DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_legacy_state_dir(default_dir: str | Path) -> Path:
    override = os.getenv(LEGACY_STATE_DIR_ENV, "").strip()
    if override:
        path = Path(override).expanduser()
    else:
        path = Path(default_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_state_dir(default_dir: str | Path) -> Path:
    if os.getenv(LEGACY_STATE_DIR_ENV, "").strip():
        # Legacy explicit override remains highest priority.
        return resolve_legacy_state_dir(default_dir)

    runtime_data_dir = resolve_runtime_data_dir()
    state_name = Path(default_dir).name.strip() or DEFAULT_STATE_SUBDIR
    path = runtime_data_dir / state_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_state_file(default_state_dir: str | Path, filename: str) -> Path:
    return resolve_state_dir(default_state_dir) / filename


def resolve_legacy_state_file(default_state_dir: str | Path, filename: str) -> Path:
    return resolve_legacy_state_dir(default_state_dir) / filename


def read_path_with_legacy_fallback(primary_path: str | Path, legacy_path: str | Path) -> Path:
    primary = Path(primary_path)
    if primary.exists():
        return primary
    legacy = Path(legacy_path)
    if legacy.exists():
        return legacy
    return primary


def seed_primary_from_legacy(primary_path: str | Path, legacy_path: str | Path) -> bool:
    """
    Copy a legacy file into the new runtime location exactly once.
    Returns True when a copy happened.
    """
    primary = Path(primary_path)
    legacy = Path(legacy_path)
    if primary.exists() or not legacy.exists() or not legacy.is_file():
        return False
    primary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, primary)
    return True
