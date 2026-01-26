import time
from api.revolut_api import place_order, get_balances, get_active_orders, cancel_order
from risk.risk_manager import RiskManager

# Configuration constants
TAKE_PROFIT_PCT = 0.03      # 3% take profit
STOP_LOSS_PCT = 0.015     # 1.5% stop loss
TRAILING_STOP_PCT = 0.012   # 1.2% trailing stop
COOLDOWN = 120             # Cooldown period in seconds
REENTRY_DELAY = 300         # Delay after selling before re-entering

# State variables
last_trade_time = 0
last_exit_time = 0
open_position = None
highest_price = None

# Risk manager instance
risk = RiskManager()

def execute_trade(signal, symbol):
    global last_trade_time, last_exit_time, open_position, highest_price

    now = time.time()

    # Re-entry delay after exiting a position
    if open_position is None and (now - last_exit_time) < REENTRY_DELAY:
        return

    # Cooldown period enforcement
    if now - last_trade_time < COOLDOWN:
        return

    # If we have no open position and the signal is to buy
    if open_position is None:
        if signal["action"] == "BUY":
            balances = get_balances()
            usdt_balance = float(next(b["available"] for b in balances if b["currency"] == "USDT"))

            entry_price = signal["price"]
            stop_price = signal["support"]

            size = risk.position_size(usdt_balance, entry_price, stop_price)
            if size <= 0:
                return

            # Cancel any existing open orders before placing a new one
            active_orders = get_active_orders()
            for order in active_orders:
                cancel_order(order["id"])
                print(f"Cancelled stale order {order['id']}")

            # Place a new buy order
            response = place_order(symbol, "BUY", size)
            print("BUY ORDER:", response)

            open_position = {
                "entry": entry_price,
                "size": size,
                "stop": stop_price
            }
            highest_price = entry_price
            last_trade_time = now
            return

    # If we have an open position, manage exits
    if open_position:
        current_price = signal["price"]
        entry = open_position["entry"]

        # Track the highest price for trailing stop
        highest_price = max(highest_price, current_price)

        # Take profit
        if current_price >= entry * (1 + TAKE_PROFIT_PCT):
            place_order(symbol, "SELL", open_position["size"])
            print("TAKE PROFIT HIT")
            _reset_position()
            return

        # Stop loss
        if current_price <= entry * (1 - STOP_LOSS_PCT):
            place_order(symbol, "SELL", open_position["size"])
            print("STOP LOSS HIT")
            _reset_position()
            return

        # Trailing stop
        trailing_stop_price = highest_price * (1 - TRAILING_STOP_PCT)
        if current_price <= trailing_stop_price:
            place_order(symbol, "SELL", open_position["size"])
            print("TRAILING STOP HIT")
            _reset_position()
            return

def _reset_position():
    global open_position, highest_price, last_exit_time
    open_position = None
    highest_price = None
    last_exit_time = time.time()
