"""
Flask control server
- Acts as the single source of truth for bot configuration
- Serves JSON-only API endpoints for the UI
- Normalizes symbols before persisting
- Never returns HTML (prevents frontend crashes)
"""

from flask import Flask, jsonify, request
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "state", "config.json")

app = Flask(__name__)


# ------------------------
# Helpers
# ------------------------

def normalize_symbol(symbol: str) -> str:
    """Normalize symbols to exchange-safe format (BTCUSDT)."""
    return symbol.replace("/", "").replace("-", "").upper()


def load_config():
    """Load config from disk safely."""
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def save_config(cfg):
    """Persist config atomically."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ------------------------
# API Routes
# ------------------------

@app.route("/config", methods=["GET"])
def get_config():
    """
    Returns full bot config.
    Always returns JSON (never HTML).
    """
    try:
        return jsonify(load_config())
    except Exception as e:
        return jsonify({"error": str(e), "config": {}}), 500


@app.route("/config", methods=["POST"])
def update_config():
    """
    Updates bot configuration.
    Symbols are normalized before saving.
    """
    try:
        cfg = request.get_json(force=True)

        if "symbols" in cfg:
            cfg["symbols"] = [normalize_symbol(s) for s in cfg["symbols"]]

        save_config(cfg)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/start", methods=["POST"])
def start_bot():
    """Enable trading loop."""
    cfg = load_config()
    cfg["enabled"] = True
    save_config(cfg)
    return jsonify({"status": "bot started"})


@app.route("/stop", methods=["POST"])
def stop_bot():
    """Disable trading loop."""
    cfg = load_config()
    cfg["enabled"] = False
    save_config(cfg)
    return jsonify({"status": "bot stopped"})


@app.route("/kill", methods=["POST"])
def kill_switch():
    """Emergency stop: disables everything."""
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
