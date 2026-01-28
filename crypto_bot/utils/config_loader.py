"""
Hot-reloading config loader
- Automatically reloads config.json when changed
- Used by bot loop for live updates
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "state", "config.json")

_last_mtime = 0
_cached = None


def load_config():
    global _last_mtime, _cached

    if not os.path.exists(CONFIG_PATH):
        return {}

    mtime = os.path.getmtime(CONFIG_PATH)
    if mtime != _last_mtime:
        with open(CONFIG_PATH, "r") as f:
            _cached = json.load(f)
        _last_mtime = mtime

    return _cached
