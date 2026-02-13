from utils.logger import setup_logger
from paper.paper_broker import PaperBroker
from risk.risk_manager import RiskManager

logger = setup_logger("executor")


class Executor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.paper = PaperBroker(cfg["starting_balance"])
        self.risk = RiskManager(cfg)
    def update_config(self, cfg: dict):
        self.cfg = cfg
        # ---------------- POSITION HELPERS ----------------

    def has_open_position(self, symbol: str) -> bool:
        return self.paper.has_position(symbol)

    def open_positions_count(self) -> int:
        return len(getattr(self.paper, "positions", {}))

    def handle_decision(self, decision: dict):
        symbol = decision["symbol"]
        action = decision["action"]
        price = decision["price"]
        reason = decision.get("reason")

        logger.info(f"Executor: {symbol} → {action} @ {price} | {reason}")

        # ---------------- BUY ----------------
        if action == "BUY":
            if not self.risk.can_trade(symbol):
                logger.info(f"Cooldown active for {symbol}")
                return

            if not self.risk.can_open_position():
                logger.info("Max concurrent trades reached")
                return

            if self.paper.has_position(symbol):
                logger.info(f"Position already open for {symbol}")
                return

            balance = self.paper.get_balance()
            size = self.risk.position_size(balance, price)

            if size <= 0:
                logger.warning("Invalid position size")
                return

            if self.paper.buy(symbol, price, size, reason):
                self.risk.mark_trade(symbol)
                self.risk.register_position(symbol, {
                    "entry": price,
                    "size": size
                })

        # ---------------- SELL ----------------
        elif action == "SELL":
            if not self.paper.has_position(symbol):
                logger.warning(f"No open position to sell for {symbol}")
                return

            if self.paper.sell(symbol, price, reason):
                self.risk.close_position(symbol)

        # ---------------- HOLD ----------------
        else:
            return



# from utils.logger import setup_logger
# from paper.paper_broker import PaperBroker
# from risk.risk_manager import RiskManager

# logger = setup_logger("executor")


# class Executor:
#     def __init__(self, cfg):
#         self.cfg = cfg
#         self.paper = PaperBroker(cfg["starting_balance"])
#         self.risk = RiskManager(cfg)
#         self.highest_price = {}

#     def handle_decision(self, decision):
#         symbol = decision["symbol"]
#         action = decision["action"]
#         price = decision["price"]

#         logger.info(f"Executor: {symbol} → {action} @ {price}")

#         if action == "BUY":
#             if not self.risk.can_trade(symbol):
#                 logger.info(f"Cooldown active for {symbol}")
#                 return

#             if not self.risk.can_open_position():
#                 logger.info("Max concurrent trades reached")
#                 return

#             if self.paper.has_position(symbol):
#                 logger.info(f"Position already open for {symbol}")
#                 return

#             balance = self.paper.get_balance()
#             size = self.risk.position_size(balance, price)

#             if size <= 0:
#                 logger.warning("Invalid position size")
#                 return

#             if self.paper.buy(symbol, size, price, reason="strategy_buy"):
#                 self.risk.mark_trade(symbol)
#                 self.risk.register_position(symbol, {
#                     "entry": price,
#                     "size": size
#                 })
#                 self.highest_price[symbol] = price

#         elif action == "SELL":
#             if not self.paper.has_position(symbol):
#                 return
#             self._exit_position(symbol, price, "strategy_sell")

#         elif self.paper.has_position(symbol):
#             self._check_exits(symbol, price)

#     def _check_exits(self, symbol, price):
#         position = self.paper.get_position(symbol)
#         entry = position["entry_price"]

#         exits = self.cfg["exits"]
#         self.highest_price[symbol] = max(
#             self.highest_price.get(symbol, entry),
#             price
#         )

#         if price <= entry * (1 - exits["stop_loss"]):
#             self._exit_position(symbol, price, "stop_loss")
#             return

#         if price >= entry * (1 + exits["take_profit"]):
#             self._exit_position(symbol, price, "take_profit")
#             return

#         trail = self.highest_price[symbol] * (1 - exits["trailing_stop"])
#         if price <= trail:
#             self._exit_position(symbol, price, "trailing_stop")

#     def _exit_position(self, symbol, price, reason):
#         if self.paper.sell(symbol, price, reason):
#             self.risk.close_position(symbol)
#             self.highest_price.pop(symbol, None)



# import time
# from utils.logger import setup_logger
# from paper.paper_broker import PaperBroker
# from risk.risk_manager import RiskManager

# logger = setup_logger()


# class Executor:
#     def __init__(self, cfg):
#         self.cfg = cfg
#         self.paper = PaperBroker()
#         self.risk = RiskManager(cfg)

#         # Track trailing stops
#         self.highest_price = {}

#     # -------------------------
#     # MAIN ENTRY
#     # -------------------------

#     def handle_decision(self, decision):
#         symbol = decision["symbol"]
#         action = decision["action"]
#         price = decision["price"]

#         logger.info(f"⚙️ Executor received {symbol} {action} @ {price}")

#         # -------------------------
#         # BUY LOGIC
#         # -------------------------

#         if action == "BUY":
#             if not self.risk.can_trade(symbol):
#                 logger.info(f"⏳ Cooldown active for {symbol}")
#                 return

#             if not self.risk.can_open_position():
#                 logger.info("🚫 Max concurrent trades reached")
#                 return

#             if self.paper.has_position(symbol):
#                 logger.info(f"📦 Position already open for {symbol}")
#                 return

#             balance = self.paper.get_balance()
#             size = self.risk.position_size(balance, price)

#             if size <= 0:
#                 logger.warning("❌ Invalid position size")
#                 return

#             if self.paper.buy(symbol, size, price, reason="strategy_buy"):
#                 self.risk.mark_trade(symbol)
#                 self.risk.register_position(symbol, {
#                     "entry": price,
#                     "size": size
#                 })
#                 self.highest_price[symbol] = price

#             return

#         # -------------------------
#         # SELL / EXIT LOGIC
#         # -------------------------

#         if action == "SELL":
#             if not self.paper.has_position(symbol):
#                 logger.info(f"📭 No position to sell for {symbol}")
#                 return

#             self._exit_position(symbol, price, reason="strategy_sell")
#             return

#         # HOLD → evaluate exits
#         if self.paper.has_position(symbol):
#             self._check_exits(symbol, price)

#     # -------------------------
#     # EXIT HANDLING
#     # -------------------------

#     def _check_exits(self, symbol, price):
#         position = self.paper.get_position(symbol)
#         entry = position["entry_price"]

#         exits = self.cfg["exits"]
#         stop_loss = exits["stop_loss"]
#         take_profit = exits["take_profit"]
#         trailing = exits["trailing_stop"]

#         # Track highest price
#         self.highest_price[symbol] = max(
#             self.highest_price.get(symbol, entry),
#             price
#         )

#         # Stop loss
#         if price <= entry * (1 - stop_loss):
#             logger.info(f"🛑 STOP LOSS hit for {symbol}")
#             self._exit_position(symbol, price, "stop_loss")
#             return

#         # Take profit
#         if price >= entry * (1 + take_profit):
#             logger.info(f"🎯 TAKE PROFIT hit for {symbol}")
#             self._exit_position(symbol, price, "take_profit")
#             return

#         # Trailing stop
#         trail_price = self.highest_price[symbol] * (1 - trailing)
#         if price <= trail_price:
#             logger.info(f"🔁 TRAILING STOP hit for {symbol}")
#             self._exit_position(symbol, price, "trailing_stop")

#     def _exit_position(self, symbol, price, reason):
#         if self.paper.sell(symbol, price, reason=reason):
#             self.risk.close_position(symbol)
#             self.highest_price.pop(symbol, None)
