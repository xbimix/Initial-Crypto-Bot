import time
from pathlib import Path

from utils.logger import setup_logger
from utils.state_storage import get_state_storage

logger = setup_logger("paper")

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
BALANCE_FILE = STATE_DIR / "paper_state.json"
TRADES_FILE = STATE_DIR / "trades.json"


class PaperBroker:
    def __init__(self, starting_balance: float):
        self.starting_balance = starting_balance
        self.balance = starting_balance
        self.positions = {}
        self._state_mtime = None
        self.storage = get_state_storage()

        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_balance_file()
        self._ensure_trades_file()
        self._load_state()

    def _ensure_balance_file(self):
        if not BALANCE_FILE.exists():
            self.storage.write(
                BALANCE_FILE,
                {"balance": self.starting_balance, "positions": {}},
            )
            self._state_mtime = self._get_state_mtime()

    def _ensure_trades_file(self):
        if not TRADES_FILE.exists():
            self.storage.write(TRADES_FILE, [])

    def _get_state_mtime(self):
        try:
            return BALANCE_FILE.stat().st_mtime
        except OSError:
            return None

    def refresh_from_disk(self, force: bool = False) -> bool:
        current_mtime = self._get_state_mtime()
        if (
            not force
            and self._state_mtime is not None
            and current_mtime is not None
            and current_mtime == self._state_mtime
        ):
            return False

        self._load_state()
        return True

    def get_balance(self) -> float:
        return self.balance

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def get_position(self, symbol: str):
        return self.positions.get(symbol)

    def _record_trade(self, trade: dict, *, use_lock: bool = True):
        try:
            data = self.storage.read(TRADES_FILE, default=[])
            if not isinstance(data, list):
                data = []
            data.append(trade)
            self.storage.write(TRADES_FILE, data, use_lock=use_lock)
        except Exception as exc:
            logger.error(f"Failed to record trade: {exc}")

    def _load_state(self):
        try:
            data = self.storage.read(
                BALANCE_FILE,
                default={"balance": self.starting_balance, "positions": {}},
            )
            if not isinstance(data, dict):
                data = {"balance": self.starting_balance, "positions": {}}

            balance = data.get("balance", self.starting_balance)
            positions = data.get("positions", {})

            try:
                self.balance = float(balance)
            except (TypeError, ValueError):
                self.balance = float(self.starting_balance)

            self.positions = positions if isinstance(positions, dict) else {}
            self._state_mtime = self._get_state_mtime()
        except Exception as exc:
            logger.error(f"Failed to load paper state: {exc}")

    def _save_state(self, *, use_lock: bool = True):
        try:
            self.storage.write(
                BALANCE_FILE,
                {"balance": self.balance, "positions": self.positions},
                use_lock=use_lock,
            )
            self._state_mtime = self._get_state_mtime()
        except Exception as exc:
            logger.error(f"Failed to save paper state: {exc}")

    def buy(self, symbol: str, price: float, size: float, reason: str):
        with self.storage.transaction(STATE_DIR):
            self._load_state()

            cost = price * size
            if cost > self.balance:
                logger.warning(f"BUY rejected - insufficient balance for {symbol}")
                return False

            self.balance -= cost
            self.positions[symbol] = {
                "price": price,
                "size": size,
                "entry_time": time.time(),
                "reason": reason,
            }

            self._record_trade(
                {
                    "time": time.time(),
                    "symbol": symbol,
                    "side": "BUY",
                    "price": price,
                    "size": size,
                    "balance": self.balance,
                    "reason": reason,
                },
                use_lock=False,
            )

            self._save_state(use_lock=False)

        logger.info(f"Paper BUY {symbol} @ {price} size={size}")
        return True

    def sell(self, symbol: str, price: float, reason: str):
        with self.storage.transaction(STATE_DIR):
            self._load_state()

            pos = self.positions.get(symbol)
            if not pos:
                logger.warning(f"SELL rejected - no open position for {symbol}")
                return False

            size = pos["size"]
            entry_price = pos["price"]
            pnl = (price - entry_price) * size

            self.balance += price * size
            del self.positions[symbol]

            self._record_trade(
                {
                    "time": time.time(),
                    "symbol": symbol,
                    "side": "SELL",
                    "price": price,
                    "size": size,
                    "pnl": pnl,
                    "balance": self.balance,
                    "reason": reason,
                },
                use_lock=False,
            )

            self._save_state(use_lock=False)

        logger.info(f"Paper SELL {symbol} @ {price} pnl={pnl:.2f}")
        return True
