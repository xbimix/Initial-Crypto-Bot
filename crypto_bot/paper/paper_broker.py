import json
import time
from pathlib import Path
from utils.logger import setup_logger

logger = setup_logger()

STATE_DIR = Path("state")
STATE_DIR.mkdir(exist_ok=True)

STATE_FILE = STATE_DIR / "paper_state.json"
TRADES_FILE = STATE_DIR / "trades.json"


class PaperBroker:
    def __init__(self, starting_balance=10_000):
        self.starting_balance = starting_balance
        self._load_state()

    # -------------------------
    # STATE
    # -------------------------

    def _load_state(self):
        if STATE_FILE.exists():
            self.state = json.loads(STATE_FILE.read_text())
        else:
            self.state = {
                "balance": self.starting_balance,
                "positions": {}
            }
            self._save_state()

        if not TRADES_FILE.exists():
            TRADES_FILE.write_text(json.dumps([], indent=2))

    def _save_state(self):
        STATE_FILE.write_text(json.dumps(self.state, indent=2))

    def _log_trade(self, trade):
        trades = json.loads(TRADES_FILE.read_text())
        trades.append(trade)
        TRADES_FILE.write_text(json.dumps(trades, indent=2))

    # -------------------------
    # PUBLIC API
    # -------------------------

    def get_balance(self):
        return self.state["balance"]

    def has_position(self, symbol):
        return symbol in self.state["positions"]

    def get_position(self, symbol):
        return self.state["positions"].get(symbol)

    # -------------------------
    # EXECUTION
    # -------------------------

    def buy(self, symbol, size, price, reason="strategy"):
        cost = size * price

        if cost > self.state["balance"]:
            logger.warning("❌ Paper BUY rejected — insufficient balance")
            return False

        if symbol in self.state["positions"]:
            logger.warning("❌ Paper BUY rejected — position exists")
            return False

        self.state["balance"] -= cost
        self.state["positions"][symbol] = {
            "symbol": symbol,
            "size": size,
            "entry_price": price,
            "entry_time": time.time()
        }

        self._save_state()

        trade = {
            "time": time.time(),
            "symbol": symbol,
            "side": "BUY",
            "price": price,
            "size": size,
            "balance_after": self.state["balance"],
            "reason": reason
        }

        self._log_trade(trade)
        logger.info(f"🧾 PAPER BUY: {trade}")
        return True

    def sell(self, symbol, price, reason="exit"):
        position = self.state["positions"].get(symbol)

        if not position:
            logger.warning("❌ Paper SELL rejected — no position")
            return False

        size = position["size"]
        entry = position["entry_price"]
        pnl = (price - entry) * size

        self.state["balance"] += size * price
        del self.state["positions"][symbol]

        self._save_state()

        trade = {
            "time": time.time(),
            "symbol": symbol,
            "side": "SELL",
            "price": price,
            "size": size,
            "pnl": pnl,
            "balance_after": self.state["balance"],
            "reason": reason
        }

        self._log_trade(trade)
        logger.info(f"🧾 PAPER SELL: {trade}")
        return True
