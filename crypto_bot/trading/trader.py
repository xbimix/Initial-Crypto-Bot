import time
from config import *

class Trader:
    def __init__(self):
        self.position_price = None
        self.last_trade_time = 0
        self.rebuy_levels = []

    def cooldown_passed(self):
        return time.time() - self.last_trade_time > COOLDOWN_PERIOD_SECONDS

    def buy(self, price):
        self.position_price = price
        self.last_trade_time = time.time()
        print(f"BUY @ {price:.2f}")

    def sell(self, price):
        profit = (price - self.position_price) / self.position_price
        print(f"SELL @ {price:.2f} | Profit {profit*100:.2f}%")
        self.position_price = None
        self.last_trade_time = time.time()

    def should_sell(self, price):
        if not self.position_price:
            return False
        profit = (price - self.position_price) / self.position_price
        return MIN_PROFIT_PERCENT <= profit <= MAX_PROFIT_PERCENT
