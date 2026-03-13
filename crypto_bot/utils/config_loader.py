"""
Hot-reloading config loader
- Automatically reloads config.json when changed
- Used by bot loop for live updates
"""
import os
from collections.abc import Callable
from pathlib import Path

from utils.config_schema import normalize_config
from utils.logger import setup_logger
from utils.state_io import mutate_json_file, read_json_file, write_json_file

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
CONFIG_PATH = STATE_DIR / "config.json"
logger = setup_logger("config_loader")

_STRICT_CONFIG_VALIDATION = os.getenv("REVBOT_CONFIG_STRICT", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_AUTOSAVE_CONFIG_NORMALIZATION = os.getenv(
    "REVBOT_CONFIG_AUTOSAVE_NORMALIZED",
    "0",
).strip().lower() in {"1", "true", "yes", "on"}
_last_warning_fingerprint: tuple[str, ...] | None = None


def _log_validation_warnings(warnings: list[str]):
    global _last_warning_fingerprint

    if not warnings:
        _last_warning_fingerprint = None
        return

    fingerprint = tuple(warnings)
    if fingerprint == _last_warning_fingerprint:
        return

    logger.warning("Config validation warnings: " + " | ".join(warnings))
    _last_warning_fingerprint = fingerprint


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.json not found")

    cfg = read_json_file(CONFIG_PATH, strict=True)
    normalized, warnings, changed = normalize_config(
        cfg,
        strict=_STRICT_CONFIG_VALIDATION,
    )
    _log_validation_warnings(warnings)

    if changed and _AUTOSAVE_CONFIG_NORMALIZATION:
        write_json_file(CONFIG_PATH, normalized)

    return normalized


def save_config(cfg):
    if not isinstance(cfg, dict):
        raise ValueError("save_config expects a dict")
    normalized, warnings, _ = normalize_config(
        cfg,
        strict=_STRICT_CONFIG_VALIDATION,
    )
    _log_validation_warnings(warnings)
    write_json_file(CONFIG_PATH, normalized)


def update_config(mutator: Callable[[dict], dict | None]):
    def _mutate(current):
        if not isinstance(current, dict):
            current = {}
        updated = mutator(current)
        if updated is None:
            updated = current
        if not isinstance(updated, dict):
            raise ValueError("update_config mutator must return a dict or None")
        normalized, warnings, _ = normalize_config(
            updated,
            strict=_STRICT_CONFIG_VALIDATION,
        )
        _log_validation_warnings(warnings)
        return normalized

    return mutate_json_file(CONFIG_PATH, _mutate, default={})
