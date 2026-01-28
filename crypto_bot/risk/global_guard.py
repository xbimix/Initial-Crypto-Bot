import json
import time
from pathlib import Path
from .limits import *

STATE_FILE = Path("state/runtime.json")

def _load():
    if not STATE_FILE.exists():
        return {
            "date": time.strftime("%Y-%m-%d"),
            "daily_loss": 0.0,
            "trades": 0,
            "exposure": {}
        }
    return json.loads(STATE_FILE.read_text())

def _save(data):
    STATE_FILE.write_text(json.dumps(data, indent=2))

def reset_if_new_day():
    data = _load()
    today = time.strftime("%Y-%m-%d")
    if data["date"] != today:
        data = {
            "date": today,
            "daily_loss": 0.0,
            "trades": 0,
            "exposure": {}
        }
        _save(data)
    return data

def can_trade(symbol, account_balance):
    data = reset_if_new_day()

    if data["daily_loss"] >= MAX_DAILY_LOSS_PERCENT * account_balance:
        return False, "Daily loss limit hit"

    if data["trades"] >= MAX_DAILY_TRADES:
        return False, "Daily trade limit hit"

    exposure = data["exposure"].get(symbol, 0)
    if exposure >= MAX_EXPOSURE_PER_SYMBOL * account_balance:
        return False, "Symbol exposure limit hit"

    return True, None

def record_trade(symbol, size, loss=0.0):
    data = reset_if_new_day()
    data["trades"] += 1
    data["daily_loss"] += abs(loss)
    data["exposure"][symbol] = data["exposure"].get(symbol, 0) + size
    _save(data)
