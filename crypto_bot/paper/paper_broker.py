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

    def buy(
        self,
        symbol: str,
        price: float,
        size: float,
        reason: str,
        trade_meta: dict | None = None,
    ):
        with self.storage.transaction(STATE_DIR):
            self._load_state()

            cost = price * size
            if cost > self.balance:
                logger.warning(f"BUY rejected - insufficient balance for {symbol}")
                return False

            self.balance -= cost
            entry_metadata = {}
            if isinstance(trade_meta, dict):
                for key in (
                    "entry_route",
                    "entry_regime",
                    "exit_policy",
                    "entry_confidence",
                    "entry_timestamp",
                    "route_eval_ts",
                    "regime_eval_ts",
                    "effective_route",
                    "effective_strategy",
                    "configured_regime",
                    "detected_regime",
                    "suggested_regime_v2",
                    "fallback_reason",
                    "auto_fallback_reason",
                ):
                    value = trade_meta.get(key)
                    if value is not None:
                        entry_metadata[key] = value

            self.positions[symbol] = {
                "price": price,
                "size": size,
                "entry_time": float(entry_metadata.get("entry_timestamp") or time.time()),
                "reason": reason,
                **entry_metadata,
            }

            trade_row = {
                "time": time.time(),
                "symbol": symbol,
                "side": "BUY",
                "price": price,
                "size": size,
                "balance": self.balance,
                "reason": reason,
            }
            if isinstance(trade_meta, dict):
                for key in (
                    "effective_route",
                    "effective_strategy",
                    "configured_regime",
                    "detected_regime",
                    "suggested_regime_v2",
                    "fallback_reason",
                    "auto_fallback_reason",
                    "entry_route",
                    "entry_regime",
                    "exit_policy",
                    "entry_confidence",
                    "entry_timestamp",
                    "route_eval_ts",
                    "regime_eval_ts",
                ):
                    value = trade_meta.get(key)
                    if value is not None:
                        trade_row[key] = value
            self._record_trade(trade_row, use_lock=False)

            self._save_state(use_lock=False)

        logger.info(f"Paper BUY {symbol} @ {price} size={size}")
        return True

    def sell(
        self,
        symbol: str,
        price: float,
        reason: str,
        trade_meta: dict | None = None,
    ):
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

            trade_row = {
                "time": time.time(),
                "symbol": symbol,
                "side": "SELL",
                "price": price,
                "size": size,
                "pnl": pnl,
                "balance": self.balance,
                "reason": reason,
            }
            trade_row["entry_route"] = pos.get("entry_route")
            trade_row["entry_regime"] = pos.get("entry_regime")
            trade_row["exit_policy_used"] = pos.get("exit_policy")
            trade_row["entry_confidence"] = pos.get("entry_confidence")
            trade_row["entry_timestamp"] = pos.get("entry_timestamp")
            trade_row["route_eval_ts"] = pos.get("route_eval_ts")
            trade_row["regime_eval_ts"] = pos.get("regime_eval_ts")
            if trade_row.get("entry_route") is not None:
                trade_row.setdefault("effective_route", trade_row.get("entry_route"))
            if isinstance(trade_meta, dict):
                for key in (
                    "effective_route",
                    "effective_strategy",
                    "configured_regime",
                    "detected_regime",
                    "suggested_regime_v2",
                    "fallback_reason",
                    "auto_fallback_reason",
                    "entry_route",
                    "entry_regime",
                    "exit_policy",
                    "exit_policy_used",
                    "entry_confidence",
                    "entry_timestamp",
                    "route_eval_ts",
                    "regime_eval_ts",
                ):
                    value = trade_meta.get(key)
                    if value is not None:
                        trade_row[key] = value
            self._record_trade(trade_row, use_lock=False)

            self._save_state(use_lock=False)

        logger.info(f"Paper SELL {symbol} @ {price} pnl={pnl:.2f}")
        return True
