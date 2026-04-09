from flask import Flask, jsonify, render_template
import json
from pathlib import Path

from utils.state_paths import read_path_with_legacy_fallback, resolve_legacy_state_file, resolve_state_file

app = Flask(__name__)

DEFAULT_STATE_DIR = Path(__file__).resolve().parent.parent / "state"
STATE_FILE = resolve_state_file(DEFAULT_STATE_DIR, "paper_state.json")
LEGACY_STATE_FILE = resolve_legacy_state_file(DEFAULT_STATE_DIR, "paper_state.json")
LOG_FILE = resolve_state_file(DEFAULT_STATE_DIR, "bot.log")
LEGACY_LOG_FILE = resolve_legacy_state_file(DEFAULT_STATE_DIR, "bot.log")


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/state")
def state():
    path = read_path_with_legacy_fallback(
        STATE_FILE,
        LEGACY_STATE_FILE,
        context="ui.web_ui.api_state",
    )
    if not path.exists():
        return jsonify({})
    with open(path, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/logs")
def logs():
    path = read_path_with_legacy_fallback(
        LOG_FILE,
        LEGACY_LOG_FILE,
        context="ui.web_ui.api_logs",
    )
    if not path.exists():
        return jsonify([])

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()[-200:]

    return jsonify(lines)


if __name__ == "__main__":
    print("STATE_FILE:", STATE_FILE, STATE_FILE.exists())
    print("LOG_FILE:", LOG_FILE, LOG_FILE.exists())
    app.run(port=5000, debug=False)
