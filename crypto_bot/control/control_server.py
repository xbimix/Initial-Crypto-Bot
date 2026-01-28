from flask import Flask, jsonify, request
import json
import os
from config import (
    MAX_RISK_PER_TRADE,
    MAX_CONCURRENT_TRADES,
    MIN_COOLDOWN_SECONDS,
    MAX_COOLDOWN_SECONDS,
    SUPPORTED_SYMBOLS
)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "state", "config.json")

app = Flask(__name__)


# ------------------------
# Utilities
# ------------------------

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def validate_config(cfg):
    # Enabled flag
    if not isinstance(cfg.get("enabled"), bool):
        raise ValueError("enabled must be boolean")

    # Symbols
    symbols = cfg.get("symbols", [])
    if not symbols or not all(s in SUPPORTED_SYMBOLS for s in symbols):
        raise ValueError("Invalid symbols")

    # Risk
    risk = cfg.get("risk", {})
    if risk["risk_per_trade"] > MAX_RISK_PER_TRADE:
        raise ValueError("Risk per trade too high")

    if risk["max_concurrent_trades"] > MAX_CONCURRENT_TRADES:
        raise ValueError("Too many concurrent trades")

    # Cooldown
    cooldown = cfg.get("cooldown_seconds", 0)
    if not (MIN_COOLDOWN_SECONDS <= cooldown <= MAX_COOLDOWN_SECONDS):
        raise ValueError("Cooldown out of bounds")


# ------------------------
# API Routes
# ------------------------

@app.route("/config", methods=["GET"])
def get_config():
    return jsonify(load_config())


@app.route("/config", methods=["POST"])
def update_config():
    new_cfg = request.json
    validate_config(new_cfg)
    save_config(new_cfg)
    return jsonify({"status": "ok"})


@app.route("/start", methods=["POST"])
def start_bot():
    cfg = load_config()
    cfg["enabled"] = True
    save_config(cfg)
    return jsonify({"status": "bot started"})


@app.route("/stop", methods=["POST"])
def stop_bot():
    cfg = load_config()
    cfg["enabled"] = False
    save_config(cfg)
    return jsonify({"status": "bot stopped"})

@app.route("/kill", methods=["POST"])
def kill():
    cfg = load_config()
    cfg["enabled"] = False
    cfg["live_trading"] = False
    save_config(cfg)
    return jsonify({"status": "KILL SWITCH ACTIVATED"})

# ------------------------
# Run
# ------------------------

if __name__ == "__main__":
    app.run(port=8001)
