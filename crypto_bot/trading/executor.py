import time
from api.revolut_api import place_order, get_balances
from risk.risk_manager import RiskManager

COOLDOWN = 120
last_trade = 0

risk = RiskManager()


def execute_trade(signal, symbol):
    global last_trade

    if signal["score"] < 70:
        return

    if time.time() - last_trade < COOLDOWN:
        return

    balances = get_balances()
    usdt = float(next(b["available"] for b in balances if b["currency"] == "USDT"))

    entry = signal["price"]
    stop = signal["support"]

    size = risk.position_size(usdt, entry, stop)
    if size <= 0:
        return

    response = place_order(symbol, "BUY", size)
    print("ORDER:", response)

    last_trade = time.time()
