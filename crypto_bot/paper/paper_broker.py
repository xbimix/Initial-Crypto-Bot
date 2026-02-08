import json
import os
import time
from utils.logger import setup_logger

logger = setup_logger("paper")

STATE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "state"))
BALANCE_FILE = os.path.join(STATE_DIR, "paper_state.json")
TRADES_FILE = os.path.join(STATE_DIR, "trades.json")


class PaperBroker:
    def __init__(self, starting_balance: float):
        self.starting_balance = starting_balance
        self.balance = starting_balance
        self.positions = {}

        os.makedirs(STATE_DIR, exist_ok=True)
        self._load_state()
        self._ensure_trades_file()

    # ---------- PUBLIC API ----------

    def get_balance(self) -> float:
        return self.balance

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def get_position(self, symbol: str):
        return self.positions.get(symbol)

    # ---------- PERSISTENCE ----------

    def _ensure_trades_file(self):
        if not os.path.exists(TRADES_FILE):
            with open(TRADES_FILE, "w") as f:
                json.dump([], f)

    def _record_trade(self, trade: dict):
        with open(TRADES_FILE, "r+") as f:
            data = json.load(f)
            data.append(trade)
            f.seek(0)
            json.dump(data, f, indent=2)

    def _load_state(self):
        if os.path.exists(BALANCE_FILE):
            with open(BALANCE_FILE, "r") as f:
                data = json.load(f)
                self.balance = data.get("balance", self.starting_balance)
                self.positions = data.get("positions", {})

    def _save_state(self):
        with open(BALANCE_FILE, "w") as f:
            json.dump(
                {"balance": self.balance, "positions": self.positions},
                f,
                indent=2,
            )

    # ---------- TRADING ----------

    def buy(self, symbol: str, price: float, size: float, reason: str):
        cost = price * size
        if cost > self.balance:
            return False

        self.balance -= cost
        self.positions[symbol] = {"price": price, "size": size}

        self._record_trade({
            "time": time.time(),
            "symbol": symbol,
            "side": "BUY",
            "price": price,
            "size": size,
            "balance": self.balance,
            "reason": reason,
        })

        self._save_state()
        logger.info(f"Paper BUY {symbol} @ {price}")
        return True

    def sell(self, symbol: str, price: float, reason: str):
        pos = self.positions.get(symbol)
        if not pos:
            return False

        size = pos["size"]
        entry = pos["price"]
        pnl = (price - entry) * size

        self.balance += price * size
        del self.positions[symbol]

        self._record_trade({
            "time": time.time(),
            "symbol": symbol,
            "side": "SELL",
            "price": price,
            "size": size,
            "pnl": pnl,
            "balance": self.balance,
            "reason": reason,
        })

        self._save_state()
        logger.info(f"Paper SELL {symbol} @ {price} pnl={pnl:.2f}")
        return True

# import json
# import os
# import time
# from utils.logger import setup_logger

# logger = setup_logger("paper")

# STATE_DIR = os.path.join(os.path.dirname(__file__), "..", "state")
# STATE_DIR = os.path.abspath(STATE_DIR)

# BALANCE_FILE = os.path.join(STATE_DIR, "paper_state.json")
# TRADES_FILE = os.path.join(STATE_DIR, "trades.json")


# class PaperBroker:
#     def __init__(self, starting_balance: float):
#         self.starting_balance = float(starting_balance)
#         self.balance = float(starting_balance)
#         self.positions = {}

#         os.makedirs(STATE_DIR, exist_ok=True)
#         self._load_state()
#         self._ensure_trades_file()

#     # ------------------------
#     # REQUIRED READ INTERFACE
#     # ------------------------

#     def get_balance(self) -> float:
#         return self.balance

#     def has_position(self, symbol: str) -> bool:
#         return symbol in self.positions

#     def get_position(self, symbol: str):
#         return self.positions.get(symbol)

#     # ------------------------
#     # Persistence
#     # ------------------------

#     def _ensure_trades_file(self):
#         if not os.path.exists(TRADES_FILE):
#             with open(TRADES_FILE, "w") as f:
#                 json.dump([], f)

#     def _record_trade(self, trade: dict):
#         try:
#             with open(TRADES_FILE, "r+") as f:
#                 data = json.load(f)
#                 data.append(trade)
#                 f.seek(0)
#                 json.dump(data, f, indent=2)
#         except Exception as e:
#             logger.error(f"Failed to persist trade: {e}")

#     def _load_state(self):
#         if os.path.exists(BALANCE_FILE):
#             try:
#                 with open(BALANCE_FILE, "r") as f:
#                     data = json.load(f)
#                     self.balance = data.get("balance", self.starting_balance)
#                     self.positions = data.get("positions", {})
#                     logger.info(f"Paper balance loaded: {self.balance}")
#             except Exception as e:
#                 logger.error(f"Failed to load paper state: {e}")
#         else:
#             self._save_state()

#     def _save_state(self):
#         try:
#             with open(BALANCE_FILE, "w") as f:
#                 json.dump(
#                     {
#                         "balance": self.balance,
#                         "positions": self.positions,
#                     },
#                     f,
#                     indent=2,
#                 )
#         except Exception as e:
#             logger.error(f"Failed to save paper state: {e}")

#     # ------------------------
#     # Trading
#     # ------------------------

#     def buy(self, symbol: str, size: float, price: float, reason: str) -> bool:
#         cost = price * size

#         if cost > self.balance:
#             logger.warning(f"BUY rejected — insufficient balance for {symbol}")
#             return False

#         if symbol in self.positions:
#             logger.warning(f"BUY rejected — position already open for {symbol}")
#             return False

#         self.balance -= cost

#         self.positions[symbol] = {
#             "symbol": symbol,
#             "size": size,
#             "entry_price": price,
#             "entry_cost": cost,
#             "opened_at": time.time(),
#             "reason": reason,
#         }

#         trade = {
#             "time": time.time(),
#             "symbol": symbol,
#             "side": "BUY",
#             "price": price,
#             "size": size,
#             "balance": self.balance,
#             "reason": reason,
#         }

#         self._record_trade(trade)
#         self._save_state()

#         logger.info(f"Paper BUY {symbol} @ {price} size={size}")
#         return True

#     def sell(self, symbol: str, price: float, reason: str) -> bool:
#         position = self.positions.get(symbol)
#         if not position:
#             logger.warning(f"SELL rejected — no open position for {symbol}")
#             return False

#         size = position["size"]
#         entry_price = position["entry_price"]
#         entry_cost = position["entry_cost"]

#         proceeds = price * size
#         pnl = proceeds - entry_cost

#         self.balance += proceeds
#         del self.positions[symbol]

#         trade = {
#             "time": time.time(),
#             "symbol": symbol,
#             "side": "SELL",
#             "price": price,
#             "size": size,
#             "pnl": pnl,
#             "balance": self.balance,
#             "reason": reason,
#         }

#         self._record_trade(trade)
#         self._save_state()

#         logger.info(
#             f"Paper SELL {symbol} @ {price} size={size} pnl={pnl:.2f}"
#         )
#         return True
