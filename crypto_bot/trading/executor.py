import time

from api.revolut_api import (
    place_order,
    get_balances,
    get_active_orders,
    cancel_order,
)

from risk.risk_manager import RiskManager
from trading.trader import PaperBroker

# ---- EXECUTION BACKENDS ----
paper = PaperBroker()
risk = RiskManager()

# ---- RUNTIME STATE ----
last_trade_time = 0
last_exit_time = 0
open_position = None
highest_price = None


def execute_trade(signal, symbol, cfg):
    """
    Executes trades based on signal and config.
    Routes orders to PAPER or LIVE execution.
    """
    global last_trade_time, last_exit_time, open_position, highest_price

    now = time.time()

    # ---- CONFIG ----
    EXECUTION_MODE = cfg.get("execution_mode", "paper")

    TAKE_PROFIT_PCT = cfg["exits"]["take_profit"]
    STOP_LOSS_PCT = cfg["exits"]["stop_loss"]
    TRAILING_STOP_PCT = cfg["exits"]["trailing_stop"]

    COOLDOWN = cfg["cooldown_seconds"]
    REENTRY_DELAY = 300
    BUY_SCORE_THRESHOLD = cfg["strategy"]["buy_score_threshold"]

    # ---- RE-ENTRY DELAY ----
    if open_position is None and (now - last_exit_time) < REENTRY_DELAY:
        return

    # ---- COOLDOWN ----
    if now - last_trade_time < COOLDOWN:
        return

    # =========================================================
    # BUY LOGIC
    # =========================================================
    if open_position is None:

        if signal.get("action") != "BUY":
            return

        if signal.get("score", 0) < BUY_SCORE_THRESHOLD:
            return

        if signal.get("regime") == "chop":
            return

        # ---- BALANCE ----
        if EXECUTION_MODE == "paper":
            balance = paper.status()["balance"]
        else:
            balances = get_balances()
            balance = float(
                next(b["available"] for b in balances if b["currency"] == "USDT")
            )

        entry_price = signal["price"]
        stop_price = signal["support"]

        confidence = signal["score"] / 100.0

        size = risk.position_size(
            balance=balance,
            entry_price=entry_price,
            stop_price=stop_price,
            confidence=confidence,
        )

        if size <= 0:
            return

        # ---- CANCEL OLD ORDERS (LIVE ONLY) ----
        if EXECUTION_MODE == "live":
            for order in get_active_orders():
                cancel_order(order["id"])

        # ---- EXECUTE BUY ----
        if EXECUTION_MODE == "paper":
            paper.buy(symbol, size, entry_price)
        else:
            place_order(symbol, "BUY", size)

        open_position = {
            "entry": entry_price,
            "size": size,
            "stop": stop_price,
        }

        highest_price = entry_price
        last_trade_time = now
        return

    # =========================================================
    # SELL / EXIT LOGIC
    # =========================================================
    if open_position:
        current_price = signal["price"]
        entry = open_position["entry"]

        highest_price = max(highest_price, current_price)

        # ---- TAKE PROFIT ----
        if current_price >= entry * (1 + TAKE_PROFIT_PCT):
            _exit_position(symbol, current_price, EXECUTION_MODE)
            return

        # ---- STOP LOSS ----
        if current_price <= entry * (1 - STOP_LOSS_PCT):
            _exit_position(symbol, current_price, EXECUTION_MODE)
            return

        # ---- TRAILING STOP ----
        trailing_stop = highest_price * (1 - TRAILING_STOP_PCT)
        if current_price <= trailing_stop:
            _exit_position(symbol, current_price, EXECUTION_MODE)
            return


def _exit_position(symbol, price, mode):
    global open_position, highest_price, last_exit_time

    if mode == "paper":
        paper.sell(symbol, price)
    else:
        place_order(symbol, "SELL", open_position["size"])

    open_position = None
    highest_price = None
    last_exit_time = time.time()
