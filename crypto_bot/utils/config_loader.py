"""
Hot-reloading config loader
- Automatically reloads config.json when changed
- Used by bot loop for live updates
"""
import json
from pathlib import Path

CONFIG_PATH = Path("state/config.json")

def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.json not found")

    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
