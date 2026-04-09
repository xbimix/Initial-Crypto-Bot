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
from utils.state_paths import (
    read_path_with_legacy_fallback,
    resolve_legacy_state_file,
    resolve_state_file,
    seed_primary_from_legacy,
)
from utils.state_io import mutate_json_file, read_json_file, write_json_file

DEFAULT_STATE_DIR = Path(__file__).resolve().parent.parent / "state"
CONFIG_PATH = resolve_state_file(DEFAULT_STATE_DIR, "config.json")
LEGACY_CONFIG_PATH = resolve_legacy_state_file(DEFAULT_STATE_DIR, "config.json")
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
_CRITICAL_WARNING_PREFIXES = (
    "risk.sizing_mode",
    "risk.stop_atr_mult_default",
    "risk.stop_atr_mult_trend",
    "risk.stop_atr_mult_breakout",
    "risk.stop_atr_mult_mean_reversion",
    "paper_execution.taker_fee_bps",
    "paper_execution.maker_fee_bps",
)


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


def _raise_for_critical_warnings(warnings: list[str]):
    critical = [
        warning
        for warning in warnings
        if any(warning.startswith(prefix) for prefix in _CRITICAL_WARNING_PREFIXES)
        and ("invalid" in warning or "below minimum" in warning or "above maximum" in warning)
    ]
    if critical:
        raise ValueError("Critical config validation failed: " + "; ".join(critical))


def load_config():
    read_path = read_path_with_legacy_fallback(
        CONFIG_PATH,
        LEGACY_CONFIG_PATH,
        context="config_loader.load_config",
    )
    if not read_path.exists():
        raise FileNotFoundError("config.json not found")

    cfg = read_json_file(read_path, strict=True)
    normalized, warnings, changed = normalize_config(
        cfg,
        strict=_STRICT_CONFIG_VALIDATION,
    )
    _raise_for_critical_warnings(warnings)
    _log_validation_warnings(warnings)

    if changed and _AUTOSAVE_CONFIG_NORMALIZATION:
        write_json_file(CONFIG_PATH, normalized)

    return normalized


def save_config(cfg):
    if not isinstance(cfg, dict):
        raise ValueError("save_config expects a dict")
    seed_primary_from_legacy(CONFIG_PATH, LEGACY_CONFIG_PATH)
    normalized, warnings, _ = normalize_config(
        cfg,
        strict=_STRICT_CONFIG_VALIDATION,
    )
    _raise_for_critical_warnings(warnings)
    _log_validation_warnings(warnings)
    write_json_file(CONFIG_PATH, normalized)


def update_config(mutator: Callable[[dict], dict | None]):
    seed_primary_from_legacy(CONFIG_PATH, LEGACY_CONFIG_PATH)

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
        _raise_for_critical_warnings(warnings)
        _log_validation_warnings(warnings)
        return normalized

    return mutate_json_file(CONFIG_PATH, _mutate, default={})
