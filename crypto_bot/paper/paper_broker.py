import json
import os
import time
from utils.logger import setup_logger

# Initialize logger (FIX)
logger = setup_logger("paper")

STATE_DIR = os.path.join(os.path.dirname(__file__), "..", "state")
STATE_DIR = os.path.abspath(STATE_DIR)

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
     

     
     
    # ------------------------
    # Persistence helpers
    # ------------------------

    def _ensure_trades_file(self):
        if not os.path.exists(TRADES_FILE):
            with open(TRADES_FILE, "w") as f:
                json.dump([], f)

    def _record_trade(self, trade: dict):
        try:
            with open(TRADES_FILE, "r+") as f:
                data = json.load(f)
                data.append(trade)
                f.seek(0)
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to persist trade: {e}")

    def _load_state(self):
        if os.path.exists(BALANCE_FILE):
            try:
                with open(BALANCE_FILE, "r") as f:
                    data = json.load(f)
                    self.balance = data.get("balance", self.starting_balance)
                    self.positions = data.get("positions", {})
                    logger.info(f"Paper balance loaded: {self.balance}")
            except Exception as e:
                logger.error(f"Failed to load paper state: {e}")
        else:
            self._save_state()

    def _save_state(self):
        try:
            with open(BALANCE_FILE, "w") as f:
                json.dump(
                    {
                        "balance": self.balance,
                        "positions": self.positions,
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"Failed to save paper state: {e}")

    # ------------------------
    # Trading actions
    # ------------------------
    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def buy(self, symbol: str, price: float, size: float, reason: str):
        cost = price * size
        if cost > self.balance:
            logger.warning(f"BUY rejected — insufficient balance for {symbol}")
            return False

        self.balance -= cost
        self.positions[symbol] = {
            "price": price,
            "size": size,
        }

        trade = {
            "time": time.time(),
            "symbol": symbol,
            "side": "BUY",
            "price": price,
            "size": size,
            "balance": self.balance,
            "reason": reason,
        }

        self._record_trade(trade)
        self._save_state()

        logger.info(f"Paper BUY {symbol} @ {price} size={size}")
        return True

    def sell(self, symbol: str, price: float, reason: str):
        if symbol not in self.positions:
            logger.warning(f"SELL rejected — no open position for {symbol}")
            return False

        entry = self.positions[symbol]
        size = entry["size"]
        entry_price = entry["price"]

        proceeds = price * size
        pnl = (price - entry_price) * size

        self.balance += proceeds
        del self.positions[symbol]

        trade = {
            "time": time.time(),
            "symbol": symbol,
            "side": "SELL",
            "price": price,
            "size": size,
            "pnl": pnl,
            "balance": self.balance,
            "reason": reason,
        }

        self._record_trade(trade)
        self._save_state()

        logger.info(f"Paper SELL {symbol} @ {price} pnl={pnl:.2f}")
        return True



# import json
# import time
# from pathlib import Path
# from utils.logger import setup_logger

# logger = setup_logger("paper")

# STATE_DIR = Path("state")
# STATE_DIR.mkdir(exist_ok=True)

# STATE_FILE = STATE_DIR / "paper_state.json"
# TRADES_FILE = STATE_DIR / "trades.json"


# class PaperBroker:
#     def __init__(self, starting_balance=10_000):
#         self.starting_balance = starting_balance
#         self._load_state()

#     def _safe_load_json(self, path, default):
#         if not path.exists():
#             return default
#         text = path.read_text().strip()
#         if not text:
#             return default
#         try:
#             return json.loads(text)
#         except Exception:
#             logger.warning(f"Corrupt JSON reset: {path}")
#             return default

#     def _safe_write_json(self, path, data):
#         tmp = path.with_suffix(".tmp")
#         tmp.write_text(json.dumps(data, indent=2))
#         tmp.replace(path)

#     def _load_state(self):
#         self.state = self._safe_load_json(
#             STATE_FILE,
#             {"balance": self.starting_balance, "positions": {}}
#         )
#         self.trades = self._safe_load_json(TRADES_FILE, [])

#         self._persist()
#         logger.info(f"Paper balance loaded: {self.state['balance']}")

#     def get_balance(self):
#         return self.state["balance"]

#     def has_position(self, symbol):
#         return symbol in self.state["positions"]

#     def get_position(self, symbol):
#         return self.state["positions"].get(symbol)

#     def buy(self, symbol, size, price, reason=None):
#         cost = size * price
#         if cost > self.state["balance"]:
#             return False

#         self.state["balance"] -= cost
#         self.state["positions"][symbol] = {
#             "size": size,
#             "entry_price": price,
#             "entry_time": time.time()
#         }

#         self.trades.append({
#             "time": time.time(),
#             "symbol": symbol,
#             "side": "BUY",
#             "price": price,
#             "size": size,
#             "balance": self.state["balance"],
#             "reason": reason
#         })

#         self._persist()
#         logger.info(f"PAPER BUY {symbol} size={size} price={price}")
#         return True

#     def sell(self, symbol, price, reason):
#         pos = self.state["positions"].pop(symbol, None)
#         if not pos:
#             return False

#         pnl = (price - pos["entry_price"]) * pos["size"]
#         self.state["balance"] += pos["size"] * price

#         self.trades.append({
#             "time": time.time(),
#             "symbol": symbol,
#             "side": "SELL",
#             "price": price,
#             "size": pos["size"],
#             "pnl": pnl,
#             "balance": self.state["balance"],
#             "reason": reason
#         })

#         self._persist()
#         logger.info(f"PAPER SELL {symbol} pnl={pnl}")
#         return True

#     def _persist(self):
#         self._safe_write_json(STATE_FILE, self.state)
#         self._safe_write_json(TRADES_FILE, self.trades)



# import json
# import time
# from pathlib import Path
# from utils.logger import setup_logger

# logger = setup_logger()

# STATE_DIR = Path("state")
# STATE_DIR.mkdir(exist_ok=True)

# STATE_FILE = STATE_DIR / "paper_state.json"
# TRADES_FILE = STATE_DIR / "trades.json"


# class PaperBroker:
#     def __init__(self, starting_balance=10_000):
#         self.starting_balance = starting_balance
#         self._load_state()

#     # =========================
#     # SAFE LOAD / SAVE
#     # =========================

#     def _safe_load_json(self, path, default):
#         try:
#             if not path.exists():
#                 return default
#             text = path.read_text().strip()
#             if not text:
#                 return default
#             return json.loads(text)
#         except Exception:
#             logger.warning(f"⚠️ Corrupt JSON detected, resetting: {path}")
#             return default

#     def _safe_write_json(self, path, data):
#         tmp = path.with_suffix(".tmp")
#         tmp.write_text(json.dumps(data, indent=2))
#         tmp.replace(path)

#     def _load_state(self):
#         self.state = self._safe_load_json(
#             STATE_FILE,
#             {
#                 "balance": self.starting_balance,
#                 "positions": {}
#             }
#         )

#         self.trades = self._safe_load_json(TRADES_FILE, [])

#         self._safe_write_json(STATE_FILE, self.state)
#         self._safe_write_json(TRADES_FILE, self.trades)

#         logger.info(
#             f"💾 Paper state loaded | balance={self.state['balance']}"
#         )

#     # =========================
#     # PUBLIC API
#     # =========================

#     def get_balance(self):
#         return self.state["balance"]

#     def has_position(self, symbol):
#         return symbol in self.state["positions"]

#     def get_position(self, symbol):
#         return self.state["positions"].get(symbol)

#     # =========================
#     # EXECUTION
#     # =========================

#     def buy(self, symbol, size, price, reason=None):
#         cost = size * price

#         if cost > self.state["balance"]:
#             logger.warning("❌ PAPER BUY rejected — insufficient balance")
#             return False

#         if symbol in self.state["positions"]:
#             logger.warning("❌ PAPER BUY rejected — position exists")
#             return False

#         self.state["balance"] -= cost
#         self.state["positions"][symbol] = {
#             "symbol": symbol,
#             "size": size,
#             "entry_price": price,
#             "entry_time": time.time()
#         }

#         trade = {
#             "time": time.time(),
#             "symbol": symbol,
#             "side": "BUY",
#             "price": price,
#             "size": size,
#             "balance_after": self.state["balance"],
#             "meta": reason or {}
#         }

#         self.trades.append(trade)
#         self._persist()

#         logger.info(f"🧾 PAPER BUY → {trade}")
#         return True

#     def sell(self, symbol, price, reason="exit"):
#         position = self.state["positions"].get(symbol)
#         if not position:
#             logger.warning("❌ PAPER SELL rejected — no position")
#             return False

#         size = position["size"]
#         entry = position["entry_price"]
#         pnl = (price - entry) * size

#         self.state["balance"] += size * price
#         del self.state["positions"][symbol]

#         trade = {
#             "time": time.time(),
#             "symbol": symbol,
#             "side": "SELL",
#             "price": price,
#             "size": size,
#             "pnl": pnl,
#             "balance_after": self.state["balance"],
#             "reason": reason
#         }

#         self.trades.append(trade)
#         self._persist()

#         logger.info(f"🧾 PAPER SELL → {trade}")
#         return True

#     # =========================
#     # PERSIST
#     # =========================

#     def _persist(self):
#         self._safe_write_json(STATE_FILE, self.state)
#         self._safe_write_json(TRADES_FILE, self.trades)
