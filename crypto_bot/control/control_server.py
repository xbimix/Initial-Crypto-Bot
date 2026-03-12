import re
import time
from pathlib import Path

from flask import Flask, jsonify, request

from utils.config_loader import load_config, update_config
from utils.logger import setup_logger
from utils.state_io import read_json_file, state_transaction_lock, write_json_file

logger = setup_logger("control")
app = Flask(__name__)

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
PAPER_STATE_PATH = STATE_DIR / "paper_state.json"
STRATEGY_STATE_PATH = STATE_DIR / "strategy_state.json"
TRADES_PATH = STATE_DIR / "trades.json"
LOG_PATH = STATE_DIR / "bot.log"
LOG_TAIL_BYTES = 256 * 1024
SNAPSHOT_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\|\s+INFO\s+\|\s+SNAPSHOT\s+([A-Z0-9-]+)\s+\|\s+price=([0-9.]+)"
)


def _normalize_symbol(value):
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def _normalize_symbols(raw_symbols):
    if not isinstance(raw_symbols, list):
        return []

    seen = set()
    normalized = []
    for raw_symbol in raw_symbols:
        symbol = _normalize_symbol(raw_symbol)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def _parse_enabled_map(value):
    if not isinstance(value, dict):
        return {}

    enabled_map = {}
    for raw_symbol, raw_enabled in value.items():
        symbol = _normalize_symbol(raw_symbol)
        if not symbol:
            continue
        enabled_map[symbol] = raw_enabled is not False
    return enabled_map


def _is_enabled(enabled_map, symbol):
    return enabled_map.get(symbol, True) is not False


def _normalize_strategy_name(value):
    raw = str(value or "").strip().lower()
    if raw in {"volatility_scalper", "vol_scalper", "scalper"}:
        return "volatility_scalper"
    return "mean_reversion"


def _remove_strategy_symbol(state, symbol):
    if not isinstance(state, dict):
        return {}

    for key in (
        "entry_price",
        "entry_time",
        "profit_lock",
        "peak_pnl",
        "last_signal",
        "last_momentum",
        "last_regime",
        "last_score",
        "last_volatility",
    ):
        section = state.get(key)
        if isinstance(section, dict):
            section.pop(symbol, None)

    return state


def _read_latest_snapshot_price(symbol):
    if not LOG_PATH.exists():
        return None

    try:
        file_size = LOG_PATH.stat().st_size
        bytes_to_read = min(LOG_TAIL_BYTES, file_size)
        if bytes_to_read <= 0:
            return None

        with open(LOG_PATH, "rb") as handle:
            handle.seek(file_size - bytes_to_read)
            tail = handle.read(bytes_to_read).decode("utf-8", errors="ignore")

        for line in reversed(tail.splitlines()):
            match = SNAPSHOT_PATTERN.match(line)
            if not match:
                continue
            if match.group(2) != symbol:
                continue

            try:
                value = float(match.group(3))
                return value if value > 0 else None
            except ValueError:
                return None

        return None
    except Exception as exc:
        logger.warning(f"Manual sell price lookup failed for {symbol}: {exc}")
        return None


def _apply_control_action(action, reason=None):
    action_key = str(action).strip().upper()

    if action_key not in {"START", "STOP", "KILL"}:
        return None, f"Unknown action: {action}"

    def _mutate(cfg):
        if not isinstance(cfg, dict):
            cfg = {}

        if action_key == "START":
            cfg["enabled"] = True
            cfg["emergency_stop"] = False
            cfg.pop("emergency_stop_at", None)
            cfg.pop("emergency_stop_reason", None)
            logger.info("Bot enabled via control server")
        elif action_key == "STOP":
            cfg["enabled"] = False
            logger.info("Bot disabled via control server")
        else:
            cfg["enabled"] = False
            cfg["emergency_stop"] = True
            cfg["emergency_stop_at"] = time.time()
            cfg["emergency_stop_reason"] = reason or "manual_kill"
            logger.warning("Emergency stop activated")

        return cfg

    cfg = update_config(_mutate)
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "emergency_stop": bool(cfg.get("emergency_stop", False)),
        "action": action_key,
    }, None


@app.route("/status", methods=["GET"])
def status():
    cfg = load_config()

    symbols = _normalize_symbols(cfg.get("symbols", []))
    symbol_enabled = _parse_enabled_map(cfg.get("symbol_enabled", {}))
    symbol_buy_enabled = _parse_enabled_map(cfg.get("symbol_buy_enabled", {}))
    symbol_sell_enabled = _parse_enabled_map(cfg.get("symbol_sell_enabled", {}))

    buy_enabled_symbols = [
        symbol
        for symbol in symbols
        if _is_enabled(symbol_buy_enabled if symbol in symbol_buy_enabled else symbol_enabled, symbol)
    ]
    sell_enabled_symbols = [
        symbol
        for symbol in symbols
        if _is_enabled(symbol_sell_enabled if symbol in symbol_sell_enabled else symbol_enabled, symbol)
    ]

    risk = cfg.get("risk", {})
    if not isinstance(risk, dict):
        risk = {}

    return jsonify(
        {
            "enabled": bool(cfg.get("enabled", False)),
            "emergency_stop": bool(cfg.get("emergency_stop", False)),
            "execution_mode": cfg.get("execution_mode"),
            "symbols": symbols,
            "buy_enabled_symbols": buy_enabled_symbols,
            "sell_enabled_symbols": sell_enabled_symbols,
            "loop_sleep": cfg.get("loop_sleep"),
            "cooldown_seconds": risk.get("cooldown_seconds"),
        }
    )


@app.route("/config", methods=["GET"])
def get_config():
    return jsonify(load_config())


@app.route("/config", methods=["POST"])
def update_config_route():
    updates = request.get_json(silent=True) or {}
    if not isinstance(updates, dict):
        return jsonify({"error": "Request body must be an object"}), 400

    def _mutate(cfg):
        cfg.update(updates)
        return cfg

    cfg = update_config(_mutate)
    logger.info(f"Config updated: {updates}")
    return jsonify({"status": "ok", "config": cfg})


@app.route("/control", methods=["POST"])
def control():
    data = request.get_json(silent=True) or {}
    action = data.get("action", "")
    reason = data.get("reason")

    payload, error = _apply_control_action(action, reason=reason)
    if error:
        return jsonify({"error": error}), 400

    return jsonify(payload)


@app.route("/kill", methods=["POST"])
def kill():
    data = request.get_json(silent=True) or {}
    reason = data.get("reason") if isinstance(data, dict) else None

    payload, error = _apply_control_action("KILL", reason=reason)
    if error:
        return jsonify({"error": error}), 400

    return jsonify(payload)


@app.route("/symbols", methods=["POST"])
def update_symbols():
    body = request.get_json(silent=True) or {}
    symbol = _normalize_symbol(body.get("symbol"))
    side_raw = body.get("side")
    enabled = body.get("enabled")

    if not symbol:
        return jsonify({"error": "Missing symbol"}), 400

    if enabled is None or not isinstance(enabled, bool):
        return jsonify({"error": "enabled must be a boolean"}), 400

    side = None
    if side_raw is not None:
        if not isinstance(side_raw, str):
            return jsonify({"error": "side must be buy, sell, or omitted"}), 400
        side = side_raw.strip().lower()
        if side not in {"buy", "sell"}:
            return jsonify({"error": "side must be buy, sell, or omitted"}), 400

    result = {}

    def _mutate(cfg):
        nonlocal result

        symbols = _normalize_symbols(cfg.get("symbols", []))
        if symbol not in symbols:
            symbols.append(symbol)

        legacy_map = _parse_enabled_map(cfg.get("symbol_enabled", {}))
        buy_map = _parse_enabled_map(cfg.get("symbol_buy_enabled", {}))
        sell_map = _parse_enabled_map(cfg.get("symbol_sell_enabled", {}))

        if side == "buy":
            buy_map[symbol] = enabled
        elif side == "sell":
            sell_map[symbol] = enabled
        else:
            buy_map[symbol] = enabled
            sell_map[symbol] = enabled
            legacy_map[symbol] = enabled

        cfg["symbols"] = symbols
        cfg["symbol_enabled"] = legacy_map
        cfg["symbol_buy_enabled"] = buy_map
        cfg["symbol_sell_enabled"] = sell_map

        result = {
            "symbol": symbol,
            "side": side,
            "enabled": enabled,
            "symbols": symbols,
            "symbol_buy_enabled": buy_map,
            "symbol_sell_enabled": sell_map,
            "symbol_enabled": legacy_map,
        }
        return cfg

    update_config(_mutate)
    return jsonify(result)


@app.route("/scalper", methods=["POST"])
def update_scalper():
    body = request.get_json(silent=True) or {}
    symbol = _normalize_symbol(body.get("symbol"))
    enabled = body.get("enabled")

    if not symbol:
        return jsonify({"error": "Missing symbol"}), 400

    if not isinstance(enabled, bool):
        return jsonify({"error": "enabled must be a boolean"}), 400

    result = {}

    def _mutate(cfg):
        nonlocal result

        symbols = _normalize_symbols(cfg.get("symbols", []))
        if symbol not in symbols:
            symbols.append(symbol)

        symbol_strategies = cfg.get("symbol_strategies", {})
        if not isinstance(symbol_strategies, dict):
            symbol_strategies = {}

        symbol_strategies[symbol] = (
            "volatility_scalper"
            if enabled
            else "mean_reversion"
        )

        scalper_cfg = cfg.get("volatility_scalper", {})
        if not isinstance(scalper_cfg, dict):
            scalper_cfg = {}

        scalper_symbols = _normalize_symbols(scalper_cfg.get("symbols", []))
        if enabled:
            if symbol not in scalper_symbols:
                scalper_symbols.append(symbol)
        else:
            scalper_symbols = [item for item in scalper_symbols if item != symbol]

        scalper_cfg["symbols"] = scalper_symbols
        cfg["symbols"] = symbols
        cfg["symbol_strategies"] = symbol_strategies
        cfg["volatility_scalper"] = scalper_cfg

        result = {
            "symbol": symbol,
            "enabled": enabled,
            "strategy": _normalize_strategy_name(symbol_strategies.get(symbol)),
            "symbol_strategies": symbol_strategies,
            "volatility_scalper": scalper_cfg,
        }
        return cfg

    update_config(_mutate)
    return jsonify(result)


@app.route("/risk", methods=["POST"])
def update_risk():
    body = request.get_json(silent=True) or {}
    max_concurrent_raw = body.get("maxConcurrentTrades")
    trade_amount_raw = body.get("tradeAmountUsd")

    if max_concurrent_raw is None and trade_amount_raw is None:
        return jsonify({"error": "No risk values provided"}), 400

    try:
        max_concurrent = (
            None
            if max_concurrent_raw is None
            else max(1, int(float(max_concurrent_raw)))
        )
    except (TypeError, ValueError):
        return jsonify({"error": "maxConcurrentTrades must be a number"}), 400

    try:
        trade_amount = (
            None
            if trade_amount_raw is None
            else max(1.0, float(trade_amount_raw))
        )
    except (TypeError, ValueError):
        return jsonify({"error": "tradeAmountUsd must be a number"}), 400

    result = {}

    def _mutate(cfg):
        nonlocal result

        risk = cfg.get("risk", {})
        if not isinstance(risk, dict):
            risk = {}

        if max_concurrent is not None:
            risk["max_concurrent_trades"] = max_concurrent
        if trade_amount is not None:
            risk["trade_amount_usd"] = trade_amount

        cfg["risk"] = risk
        result = {
            "risk": risk,
            "maxConcurrentTrades": risk.get("max_concurrent_trades"),
            "tradeAmountUsd": risk.get("trade_amount_usd"),
        }
        return cfg

    update_config(_mutate)
    return jsonify(result)


@app.route("/manual-sell", methods=["POST"])
def manual_sell():
    body = request.get_json(silent=True) or {}
    symbol = _normalize_symbol(body.get("symbol"))

    if not symbol:
        return jsonify({"error": "Missing symbol"}), 400

    with state_transaction_lock(STATE_DIR, timeout=12.0):
        paper_state = read_json_file(PAPER_STATE_PATH, default={})
        strategy_state = read_json_file(STRATEGY_STATE_PATH, default={})
        trades = read_json_file(TRADES_PATH, default=[])

        if not isinstance(paper_state, dict):
            paper_state = {}
        if not isinstance(strategy_state, dict):
            strategy_state = {}
        if not isinstance(trades, list):
            trades = []

        positions = paper_state.get("positions", {})
        if not isinstance(positions, dict):
            positions = {}

        position = positions.get(symbol)
        if not isinstance(position, dict):
            return jsonify({"error": f"No open position for {symbol}"}), 404

        try:
            entry_price = float(position.get("price", 0))
            size = float(position.get("size", 0))
        except (TypeError, ValueError):
            return jsonify({"error": f"Invalid position data for {symbol}"}), 422

        if entry_price <= 0 or size <= 0:
            return jsonify({"error": f"Invalid position data for {symbol}"}), 422

        market_price = _read_latest_snapshot_price(symbol)
        sell_price = market_price if market_price and market_price > 0 else entry_price
        if sell_price <= 0:
            return jsonify({"error": f"Unable to determine sell price for {symbol}"}), 422

        try:
            previous_balance = float(paper_state.get("balance", 0))
        except (TypeError, ValueError):
            previous_balance = 0.0

        pnl = (sell_price - entry_price) * size
        proceeds = sell_price * size
        next_balance = previous_balance + proceeds

        positions.pop(symbol, None)
        paper_state["positions"] = positions
        paper_state["balance"] = next_balance

        strategy_state = _remove_strategy_symbol(strategy_state, symbol)

        trade_entry = {
            "time": time.time(),
            "symbol": symbol,
            "side": "SELL",
            "price": sell_price,
            "size": size,
            "pnl": pnl,
            "balance": next_balance,
            "reason": "manual_user_sell",
        }
        trades.append(trade_entry)

        write_json_file(PAPER_STATE_PATH, paper_state)
        write_json_file(STRATEGY_STATE_PATH, strategy_state)
        write_json_file(TRADES_PATH, trades)

    logger.info(
        f"Manual SELL {symbol} @ {sell_price:.6f} size={size:.6f} pnl={pnl:.2f}"
    )

    return jsonify(
        {
            "status": "ok",
            "symbol": symbol,
            "price": sell_price,
            "size": size,
            "pnl": pnl,
            "balance": next_balance,
            "reason": trade_entry["reason"],
        }
    )


def run():
    logger.info("Control server starting on port 8001")
    app.run(host="127.0.0.1", port=8001, debug=False)
