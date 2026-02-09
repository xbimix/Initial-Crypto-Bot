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
        try:
            if not os.path.exists(TRADES_FILE):
                with open(TRADES_FILE, "w") as f:
                    json.dump([], f)

            with open(TRADES_FILE, "r+") as f:
                try:
                    data = json.load(f)
                    if not isinstance(data, list):
                        data = []
                except json.JSONDecodeError:
                    data = []

                data.append(trade)

                f.seek(0)
                f.truncate()
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error(f"Failed to record trade: {e}")

    def _load_state(self):
        if os.path.exists(BALANCE_FILE):
            try:
                with open(BALANCE_FILE, "r") as f:
                    data = json.load(f)
                    self.balance = data.get("balance", self.starting_balance)
                    self.positions = data.get("positions", {})
            except Exception as e:
                logger.error(f"Failed to load paper state: {e}")

    def _save_state(self):
        try:
            with open(BALANCE_FILE, "w") as f:
                json.dump(
                    {"balance": self.balance, "positions": self.positions},
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"Failed to save paper state: {e}")

    # ---------- TRADING ----------

    def buy(self, symbol: str, price: float, size: float, reason: str):
        cost = price * size
        if cost > self.balance:
            logger.warning(f"BUY rejected — insufficient balance for {symbol}")
            return False

        self.balance -= cost
        self.positions[symbol] = {
            "price": price,
            "size": size,
            "entry_time": time.time(),
            "reason": reason,
        }

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
        logger.info(f"Paper BUY {symbol} @ {price} size={size}")
        return True

    def sell(self, symbol: str, price: float, reason: str):
        pos = self.positions.get(symbol)
        if not pos:
            logger.warning(f"SELL rejected — no open position for {symbol}")
            return False

        size = pos["size"]
        entry_price = pos["price"]
        pnl = (price - entry_price) * size

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

# STATE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "state"))
# BALANCE_FILE = os.path.join(STATE_DIR, "paper_state.json")
# TRADES_FILE = os.path.join(STATE_DIR, "trades.json")


# class PaperBroker:
#     def __init__(self, starting_balance: float):
#         self.starting_balance = starting_balance
#         self.balance = starting_balance
#         self.positions = {}

#         os.makedirs(STATE_DIR, exist_ok=True)
#         self._load_state()
#         self._ensure_trades_file()

#     # ---------- PUBLIC API ----------

#     def get_balance(self) -> float:
#         return self.balance

#     def has_position(self, symbol: str) -> bool:
#         return symbol in self.positions

#     def get_position(self, symbol: str):
#         return self.positions.get(symbol)

#     # ---------- PERSISTENCE ----------

#     def _ensure_trades_file(self):
#         if not os.path.exists(TRADES_FILE):
#             with open(TRADES_FILE, "w") as f:
#                 json.dump([], f)

#     def _record_trade(self, trade: dict):
#         with open(TRADES_FILE, "r+") as f:
#             data = json.load(f)
#             data.append(trade)
#             f.seek(0)
#             json.dump(data, f, indent=2)

#     def _load_state(self):
#         if os.path.exists(BALANCE_FILE):
#             with open(BALANCE_FILE, "r") as f:
#                 data = json.load(f)
#                 self.balance = data.get("balance", self.starting_balance)
#                 self.positions = data.get("positions", {})

#     def _save_state(self):
#         with open(BALANCE_FILE, "w") as f:
#             json.dump(
#                 {"balance": self.balance, "positions": self.positions},
#                 f,
#                 indent=2,
#             )

#     # ---------- TRADING ----------

#     def buy(self, symbol: str, price: float, size: float, reason: str):
#         cost = price * size
#         if cost > self.balance:
#             return False

#         self.balance -= cost
#         self.positions[symbol] = {"price": price, "size": size}

#         self._record_trade({
#             "time": time.time(),
#             "symbol": symbol,
#             "side": "BUY",
#             "price": price,
#             "size": size,
#             "balance": self.balance,
#             "reason": reason,
#         })

#         self._save_state()
#         logger.info(f"Paper BUY {symbol} @ {price}")
#         return True

#     def sell(self, symbol: str, price: float, reason: str):
#         pos = self.positions.get(symbol)
#         if not pos:
#             return False

#         size = pos["size"]
#         entry = pos["price"]
#         pnl = (price - entry) * size

#         self.balance += price * size
#         del self.positions[symbol]

#         self._record_trade({
#             "time": time.time(),
#             "symbol": symbol,
#             "side": "SELL",
#             "price": price,
#             "size": size,
#             "pnl": pnl,
#             "balance": self.balance,
#             "reason": reason,
#         })

#         self._save_state()
#         logger.info(f"Paper SELL {symbol} @ {price} pnl={pnl:.2f}")
#         return True

