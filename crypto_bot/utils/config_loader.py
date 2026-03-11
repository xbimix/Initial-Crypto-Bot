"""
Hot-reloading config loader
- Automatically reloads config.json when changed
- Used by bot loop for live updates
"""
from collections.abc import Callable
from pathlib import Path

from utils.state_io import mutate_json_file, read_json_file, write_json_file

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
CONFIG_PATH = STATE_DIR / "config.json"


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.json not found")

    cfg = read_json_file(CONFIG_PATH, strict=True)
    if not isinstance(cfg, dict):
        raise ValueError("config.json must contain an object")
    return cfg


def save_config(cfg):
    if not isinstance(cfg, dict):
        raise ValueError("save_config expects a dict")
    write_json_file(CONFIG_PATH, cfg)


def update_config(mutator: Callable[[dict], dict | None]):
    def _mutate(current):
        if not isinstance(current, dict):
            current = {}
        updated = mutator(current)
        if updated is None:
            return current
        if not isinstance(updated, dict):
            raise ValueError("update_config mutator must return a dict or None")
        return updated

    return mutate_json_file(CONFIG_PATH, _mutate, default={})
