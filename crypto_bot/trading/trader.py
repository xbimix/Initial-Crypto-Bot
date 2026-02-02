import json
import time
from pathlib import Path

from utils.logger import setup_logger
logger = setup_logger("paper_trader")


STATE_FILE = Path("state/paper_state.json")
JOURNAL_FILE = Path("state/trades.json")

STARTING_BALANCE = 10_000.0  # USDT


class PaperBroker:
    def __init__(self):
        self.state = self._load_state()

    def _load_state(self):
        if not STATE_FILE.exists():
            return {
                "balance": STARTING_BALANCE,
                "position": None,
                "equity": STARTING_BALANCE,
            }
        return json.loads(STATE_FILE.read_text())

    def _save_state(self):
        STATE_FILE.write_text(json.dumps(self.state, indent=2))

    def _log_trade(self, trade):
        if not JOURNAL_FILE.exists():
            JOURNAL_FILE.write_text("[]")

        trades = json.loads(JOURNAL_FILE.read_text())
        trades.append(trade)
        JOURNAL_FILE.write_text(json.dumps(trades, indent=2))

    # -------------------------
    # SIMULATED EXECUTION
    # -------------------------

    def buy(self, symbol, size, price):
        cost = size * price
        if cost > self.state["balance"]:
            return False

        self.state["balance"] -= cost
        self.state["position"] = {
            "symbol": symbol,
            "size": size,
            "entry": price,
            "time": time.time(),
        }
        self._save_state()

        self._log_trade({
            "time": time.time(),
            "symbol": symbol,
            "side": "BUY",
            "size": size,
            "price": price,
            "balance": self.state["balance"],
        })
        return True

    def sell(self, symbol, price):
        pos = self.state["position"]
        if not pos:
            return False

        proceeds = pos["size"] * price
        pnl = proceeds - (pos["size"] * pos["entry"])

        self.state["balance"] += proceeds
        self.state["equity"] = self.state["balance"]
        self.state["position"] = None
        self._save_state()

        self._log_trade({
            "time": time.time(),
            "symbol": symbol,
            "side": "SELL",
            "size": pos["size"],
            "entry": pos["entry"],
            "exit": price,
            "pnl": round(pnl, 2),
            "balance": self.state["balance"],
        })
        return True

    def status(self):
        return self.state
