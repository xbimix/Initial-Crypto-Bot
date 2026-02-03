from flask import Flask, jsonify, render_template
import json
import os

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(BASE_DIR, "state", "paper_state.json")
LOG_FILE = os.path.join(BASE_DIR, "state", "bot.log")


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/state")
def state():
    if not os.path.exists(STATE_FILE):
        return jsonify({})
    with open(STATE_FILE, "r") as f:
        return jsonify(json.load(f))


@app.route("/api/logs")
def logs():
    if not os.path.exists(LOG_FILE):
        return jsonify([])

    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()[-200:]

    return jsonify(lines)


if __name__ == "__main__":
    print("BASE_DIR:", BASE_DIR)
    print("STATE_FILE:", STATE_FILE, os.path.exists(STATE_FILE))
    print("LOG_FILE:", LOG_FILE, os.path.exists(LOG_FILE))
    app.run(port=5000, debug=False)
