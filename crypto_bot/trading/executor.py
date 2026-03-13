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
        self._daily_loss_close_all_day = None
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

    def _current_allocated_usd(self):
        allocated = 0.0
        by_symbol = {}
        for symbol, pos in self.paper.positions.items():
            entry_price = float(pos.get("price", 0.0) or 0.0)
            entry_size = float(pos.get("size", 0.0) or 0.0)
            position_value = max(entry_price, 0.0) * max(entry_size, 0.0)
            allocated += position_value
            by_symbol[symbol] = position_value
        return allocated, by_symbol

    def enforce_daily_loss_controls(self, snapshot_fetcher=None):
        state = self.risk.daily_loss_state()
        if not state.get("close_all", False):
            return False

        day_key = state.get("day")
        if day_key and self._daily_loss_close_all_day == day_key:
            return False

        open_symbols = self.open_symbols()
        if not open_symbols:
            self._daily_loss_close_all_day = day_key
            return False

        closed = 0
        for symbol in list(open_symbols):
            sell_price = None
            if callable(snapshot_fetcher):
                try:
                    snapshot = snapshot_fetcher(symbol, self.cfg)
                except Exception:
                    snapshot = None
                if isinstance(snapshot, dict):
                    try:
                        price_candidate = float(snapshot.get("price", 0))
                        if price_candidate > 0:
                            sell_price = price_candidate
                    except (TypeError, ValueError):
                        sell_price = None

            if sell_price is None:
                position = self.paper.get_position(symbol) or {}
                try:
                    fallback_price = float(position.get("price", 0))
                    sell_price = fallback_price if fallback_price > 0 else None
                except (TypeError, ValueError):
                    sell_price = None

            if sell_price is None:
                continue

            if self._handle_sell(symbol, sell_price, "daily_loss_limit_close_all"):
                closed += 1

        self._daily_loss_close_all_day = day_key
        if closed > 0:
            logger.warning(
                f"Daily loss close-all executed: closed={closed} "
                f"realized_today={state.get('realized_usd', 0.0):.2f} "
                f"limit={state.get('limit_usd', 0.0):.2f}"
            )
        return closed > 0

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
        volatility = decision.get("volatility")

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
            return self._handle_buy(symbol, price, reason, volatility)

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

    def _handle_buy(self, symbol: str, price: float, reason: str, volatility=None) -> bool:

        # UTC trade window control (entries only).
        if not self.risk.is_within_trade_window():
            logger.info(f"BUY blocked for {symbol} (outside UTC trade window)")
            return False

        # Daily loss guard with buy auto-pause.
        daily_loss_state = self.risk.daily_loss_state()
        if daily_loss_state.get("buy_paused", False):
            logger.info(
                f"BUY blocked for {symbol} (daily loss limit reached: "
                f"{daily_loss_state.get('realized_usd', 0.0):.2f} <= "
                f"-{daily_loss_state.get('limit_usd', 0.0):.2f})"
            )
            return False

        # Cooldown protection
        if not self.risk.can_trade(symbol, volatility=volatility):
            logger.info(f"Cooldown active for {symbol}")
            return False

        # Maximum open trades protection
        if not self.risk.can_open_position(self.open_positions_count()):
            logger.info("Max concurrent trades reached")
            return False

        symbol_open_positions = 1 if self.paper.has_position(symbol) else 0
        if not self.risk.can_open_position_for_symbol(symbol_open_positions):
            logger.info(f"Max concurrent trades reached for {symbol}")
            return False

        # Already holding protection
        if self.paper.has_position(symbol):
            logger.info(f"Position already open for {symbol}")
            return False

        # Position sizing
        balance = self.paper.get_balance()
        size = self.risk.position_size(balance, price, volatility=volatility)

        if size <= 0:
            logger.warning("Invalid position size")
            return False

        trade_cost = price * size
        current_allocated, per_symbol_allocated = self._current_allocated_usd()
        current_symbol_allocated = per_symbol_allocated.get(symbol, 0.0)
        equity = max(balance, 0.0) + max(current_allocated, 0.0)

        if not self.risk.can_open_under_max_trade_amount(current_allocated, trade_cost):
            logger.info("Max trade amount reached")
            return False

        exposure_block_reason = self.risk.exposure_block_reason(
            current_open_value_usd=current_allocated,
            current_symbol_value_usd=current_symbol_allocated,
            next_trade_cost_usd=trade_cost,
            equity_usd=equity,
        )
        if exposure_block_reason:
            logger.info(f"BUY blocked for {symbol} ({exposure_block_reason})")
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


