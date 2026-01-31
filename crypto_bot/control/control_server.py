from flask import Flask, jsonify, request
from utils.logger import setup_logger
from utils.config_loader import load_config, save_config

logger = setup_logger()
app = Flask(__name__)


# -------------------------
# STATUS
# -------------------------

@app.route("/status", methods=["GET"])
def status():
    cfg = load_config()
    return jsonify({
        "enabled": cfg.get("enabled", False),
        "execution_mode": cfg.get("execution_mode"),
        "symbols": cfg.get("symbols"),
        "interval": cfg.get("interval")
    })


# -------------------------
# CONFIG
# -------------------------

@app.route("/config", methods=["GET"])
def get_config():
    return jsonify(load_config())


@app.route("/config", methods=["POST"])
def update_config():
    cfg = load_config()
    updates = request.json or {}

    cfg.update(updates)
    save_config(cfg)

    logger.info(f"⚙️ Config updated: {updates}")
    return jsonify({"status": "ok"})


# -------------------------
# CONTROL
# -------------------------

@app.route("/control", methods=["POST"])
def control():
    data = request.json or {}
    action = data.get("action")

    cfg = load_config()

    if action == "START":
        cfg["enabled"] = True
        logger.info("▶️ Bot ENABLED via control server")

    elif action == "STOP":
        cfg["enabled"] = False
        logger.info("⏹ Bot DISABLED via control server")

    save_config(cfg)
    return jsonify({"enabled": cfg["enabled"]})


# -------------------------
# ENTRY
# -------------------------

def run():
    logger.info("🌐 Control server starting on port 8001")
    app.run(host="127.0.0.1", port=8001, debug=False)
