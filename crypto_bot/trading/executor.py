from utils.logger import setup_logger
from paper.paper_broker import PaperBroker
from risk.risk_manager import RiskManager
from strategy.strategy_engine import confirm_entry, confirm_exit
logger = setup_logger("executor")


class Executor:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.paper = PaperBroker(cfg["starting_balance"])
        self.risk = RiskManager(cfg)
        self._sync_risk_with_broker()

    # --------------------------------------------------
    # HOT RELOAD SUPPORT
    # --------------------------------------------------

    def update_config(self, cfg: dict):
        """
        Allows dynamic config reload without restarting bot.
        """
        self.cfg = cfg
        if hasattr(self.paper, "refresh_from_disk"):
            if self.paper.refresh_from_disk():
                logger.info("Executor sync: refreshed paper state from disk")
                self._sync_risk_with_broker()
        if hasattr(self.risk, "update_config"):
            self.risk.update_config(cfg)

    # --------------------------------------------------
    # POSITION HELPERS
    # --------------------------------------------------

    def has_open_position(self, symbol: str) -> bool:
        return self.paper.has_position(symbol)

    def open_symbols(self) -> list[str]:
        return list(self.paper.positions.keys())

    def open_positions_count(self) -> int:
        return len(self.paper.positions)

    # --------------------------------------------------
    # MAIN EXECUTION ENTRY
    # --------------------------------------------------

    def handle_decision(self, decision: dict) -> bool:
        """
        Executes strategy decision.
        Returns True if trade executed.
        Returns False otherwise.
        """
        symbol = decision.get("symbol")
        action = decision.get("action")
        price = decision.get("price")
        reason = decision.get("reason")

        if not symbol or action not in {"BUY", "SELL", "HOLD"}:
            logger.warning(f"Invalid decision payload: {decision}")
            return False

        try:
            price = float(price)
        except (TypeError, ValueError):
            logger.warning(f"Invalid decision price for {symbol}: {price}")
            return False

        logger.info(f"Executor: {symbol} -> {action} @ {price} | {reason}")

        if action == "BUY":
            return self._handle_buy(symbol, price, reason)

        elif action == "SELL":
            return self._handle_sell(symbol, price, reason)

        return False
    def _sync_risk_with_broker(self):
        """
        Keep RiskManager in sync with restored broker positions when supported.
        """
        if not hasattr(self.risk, "register_position"):
            return

        for symbol, pos in self.paper.positions.items():
            self.risk.register_position(
                symbol,
                {
                    "entry": pos.get("price"),
                    "size": pos.get("size"),
                },
            )

        if self.paper.positions:
            logger.info("Executor sync: RiskManager aligned with broker state")
    # --------------------------------------------------
    # BUY HANDLER
    # --------------------------------------------------

    def _handle_buy(self, symbol: str, price: float, reason: str) -> bool:

        # Cooldown protection
        if not self.risk.can_trade(symbol):
            logger.info(f"Cooldown active for {symbol}")
            return False

        # Maximum open trades protection
        if not self.risk.can_open_position(self.open_positions_count()):
            logger.info("Max concurrent trades reached")
            return False

        # Already holding protection
        if self.paper.has_position(symbol):
            logger.info(f"Position already open for {symbol}")
            return False

        # Position sizing
        balance = self.paper.get_balance()
        size = self.risk.position_size(balance, price)

        if size <= 0:
            logger.warning("Invalid position size")
            return False

        # Execute buy
        if self.paper.buy(symbol, price, size, reason):
            self.risk.mark_trade(symbol)
            # self.risk.register_position(symbol, {
            #     "entry": price,
            #     "size": size
            # })
             # --- NEW: confirm entry to strategy ---
            
            confirm_entry(symbol, price)

            return True

        return False

    # --------------------------------------------------
    # SELL HANDLER
    # --------------------------------------------------

    def _handle_sell(self, symbol: str, price: float, reason: str) -> bool:

        # Must have position
        if not self.paper.has_position(symbol):
            logger.warning(f"No open position to sell for {symbol}")
            # Heal stale strategy state if broker is already flat.
            confirm_exit(symbol, price)
            return False

        # Execute sell
        if self.paper.sell(symbol, price, reason):
            self.risk.mark_trade(symbol)
            if hasattr(self.risk, "close_position"):
                self.risk.close_position(symbol)
            confirm_exit(symbol, price)
            return True

        return False




# from utils.logger import setup_logger
# from paper.paper_broker import PaperBroker
# from risk.risk_manager import RiskManager

# logger = setup_logger("executor")


# class Executor:
#     def __init__(self, cfg: dict):
#         self.cfg = cfg

#         # Core components
#         self.paper = PaperBroker(cfg["starting_balance"])
#         self.risk = RiskManager(cfg)

#         # --- Sync RiskManager with restored broker positions ---
#         self._sync_risk_with_broker()

#     # --------------------------------------------------
#     # CONFIG HOT RELOAD
#     # --------------------------------------------------

#     def update_config(self, cfg: dict):
#         """
#         Allows runtime config reload without restarting bot.
#         """
#         self.cfg = cfg
#         self.risk.update_config(cfg)

#     # --------------------------------------------------
#     # STARTUP SYNC
#     # --------------------------------------------------

#     def _sync_risk_with_broker(self):
#         """
#         Ensures RiskManager matches PaperBroker positions
#         after restart.
#         """
#         for symbol, pos in self.paper.positions.items():
#             self.risk.register_position(symbol, {
#                 "entry": pos["price"],
#                 "size": pos["size"]
#             })

#         if self.paper.positions:
#             logger.info("Executor sync: RiskManager aligned with broker state")

#     # --------------------------------------------------
#     # POSITION HELPERS
#     # --------------------------------------------------

#     def has_open_position(self, symbol: str) -> bool:
#         return self.paper.has_position(symbol)

#     def open_positions_count(self) -> int:
#         return len(self.paper.positions)

#     # --------------------------------------------------
#     # MAIN EXECUTION ROUTER
#     # --------------------------------------------------

#     def handle_decision(self, decision: dict):
#         symbol = decision["symbol"]
#         action = decision["action"]
#         price = decision["price"]
#         reason = decision.get("reason")

#         logger.info(f"Executor: {symbol} → {action} @ {price} | {reason}")

#         if action == "BUY":
#             self._handle_buy(symbol, price, reason)

#         elif action == "SELL":
#             self._handle_sell(symbol, price, reason)

#         else:
#             # HOLD
#             return

#     # --------------------------------------------------
#     # BUY LOGIC
#     # --------------------------------------------------

#     def _handle_buy(self, symbol: str, price: float, reason: str):

#         # Cooldown check
#         if not self.risk.can_trade(symbol):
#             logger.info(f"Cooldown active for {symbol}")
#             return

#         # Max concurrent positions check
#         if not self.risk.can_open_position():
#             logger.info("Max concurrent trades reached")
#             return

#         # Prevent duplicate position
#         if self.paper.has_position(symbol):
#             logger.info(f"Position already open for {symbol}")
#             return

#         # Position sizing
#         balance = self.paper.get_balance()
#         size = self.risk.position_size(balance, price)

#         if size <= 0:
#             logger.warning("Invalid position size")
#             return

#         # Execute buy
#         if self.paper.buy(symbol, price, size, reason):
#             self.risk.mark_trade(symbol)
#             self.risk.register_position(symbol, {
#                 "entry": price,
#                 "size": size
#             })

#     # --------------------------------------------------
#     # SELL LOGIC
#     # --------------------------------------------------

#     def _handle_sell(self, symbol: str, price: float, reason: str):

#         # Broker is source of truth
#         if not self.paper.has_position(symbol):
#             logger.warning(f"No open position to sell for {symbol}")
#             return

#         if self.paper.sell(symbol, price, reason):
#             # Apply cooldown after sell (symmetrical behaviour)
#             self.risk.mark_trade(symbol)
#             self.risk.close_position(symbol)



# from utils.logger import setup_logger
# from paper.paper_broker import PaperBroker
# from risk.risk_manager import RiskManager

# logger = setup_logger("executor")


# class Executor:
#     def __init__(self, cfg):
#         self.cfg = cfg
#         self.paper = PaperBroker(cfg["starting_balance"])
#         self.risk = RiskManager(cfg)
#     # Sync RiskManager with broker state
#         for symbol, pos in self.paper.positions.items():
#             self.risk.register_position(symbol, {
#             "entry": pos["price"],
#             "size": pos["size"]
#             })


#     def update_config(self, cfg: dict):
#         self.cfg = cfg
#         self.risk.update_config(cfg)
#         # ---------------- POSITION HELPERS ----------------

#     def has_open_position(self, symbol: str) -> bool:
#         return self.paper.has_position(symbol)

#     def open_positions_count(self) -> int:
#         return len(self.paper.positions)
#         #return len(getattr(self.paper, "positions", {}))

#     def handle_decision(self, decision: dict):
#         symbol = decision["symbol"]
#         action = decision["action"]
#         price = decision["price"]
#         reason = decision.get("reason")

#         logger.info(f"Executor: {symbol} → {action} @ {price} | {reason}")

#         # ---------------- BUY ----------------
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

#             if self.paper.buy(symbol, price, size, reason):
#                 self.risk.mark_trade(symbol)
#                 self.risk.register_position(symbol, {
#                     "entry": price,
#                     "size": size
#                 })

#         # ---------------- SELL ----------------
#         elif action == "SELL":
#             if not self.paper.has_position(symbol):
#                 logger.warning(f"No open position to sell for {symbol}")
#                 return

#             if self.paper.sell(symbol, price, reason):
#                 self.risk.close_position(symbol)

#         # ---------------- HOLD ----------------
#         else:
#             return




