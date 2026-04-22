from __future__ import annotations

import os
import shutil
import logging
from pathlib import Path


BOT_DATA_DIR_ENV = "BOT_DATA_DIR"
LEGACY_STATE_DIR_ENV = "REVBOT_STATE_DIR"
LEGACY_FALLBACK_ENV = "REVBOT_ENABLE_LEGACY_STATE_FALLBACK"
DEFAULT_RUNTIME_DATA_DIR = ".runtime"
DEFAULT_STATE_SUBDIR = "state"
_FALLBACK_WARNED_KEYS: set[tuple[str, str]] = set()
_LOGGER = logging.getLogger("state_paths")


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


def legacy_state_fallback_enabled() -> bool:
    raw = os.getenv(LEGACY_FALLBACK_ENV, "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def read_path_with_legacy_fallback(
    primary_path: str | Path,
    legacy_path: str | Path,
    *,
    context: str | None = None,
    emit_warning: bool = True,
) -> Path:
    primary = Path(primary_path)
    if primary.exists() or not legacy_state_fallback_enabled():
        return primary
    legacy = Path(legacy_path)
    if legacy.exists():
        if emit_warning:
            key = (str(primary.resolve()), str(legacy.resolve()))
            if key not in _FALLBACK_WARNED_KEYS:
                _FALLBACK_WARNED_KEYS.add(key)
                detail = f" [{context}]" if context else ""
                _LOGGER.warning(
                    "Legacy state fallback in use%s: primary_missing=%s legacy=%s",
                    detail,
                    primary,
                    legacy,
                )
        return legacy
    return primary


def seed_primary_from_legacy(primary_path: str | Path, legacy_path: str | Path) -> bool:
    """
    Copy a legacy file into the new runtime location exactly once.
    Returns True when a copy happened.
    """
    if not legacy_state_fallback_enabled():
        return False
    primary = Path(primary_path)
    legacy = Path(legacy_path)
    if primary.exists() or not legacy.exists() or not legacy.is_file():
        return False
    primary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, primary)
    return True
