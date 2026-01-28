import json
import os
import time

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "state", "config.json")

_last_mtime = 0
_cached_config = None


def load_config():
    """
    Hot-reloads config.json if it changed.
    Cached between reads for performance.
    """
    global _last_mtime, _cached_config

    mtime = os.path.getmtime(CONFIG_PATH)
    if mtime != _last_mtime:
        with open(CONFIG_PATH, "r") as f:
            _cached_config = json.load(f)
        _last_mtime = mtime

    return _cached_config
