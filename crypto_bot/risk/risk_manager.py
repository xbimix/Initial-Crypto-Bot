import json
import os
import time
from datetime import datetime, timezone

from utils.logger import setup_logger

logger = setup_logger("risk")

STATE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "state")
)
PAPER_STATE_FILE = os.path.join(STATE_DIR, "paper_state.json")
TRADES_FILE = os.path.join(STATE_DIR, "trades.json")


class RiskManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.last_trade_time = {}
        self.open_positions = {}
        self._daily_loss_cache = {
            "day": None,
            "trades_mtime": None,
            "trades_size": None,
            "realized_usd": 0.0,
        }
        self._sync_with_broker_state()

    # =====================================================
    # SYNC OPEN POSITIONS FROM PAPER STATE (RESTART SAFE)
    # =====================================================

    def _sync_with_broker_state(self):
        if not os.path.exists(PAPER_STATE_FILE):
            self.open_positions = {}
            return

        try:
            with open(PAPER_STATE_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
            positions = payload.get("positions", {}) if isinstance(payload, dict) else {}
            if not isinstance(positions, dict):
                positions = {}
            synced = {}
            for raw_symbol, row in positions.items():
                symbol = self._normalize_symbol(raw_symbol)
                if not symbol or not isinstance(row, dict):
                    continue
                synced[symbol] = {
                    "entry": self._as_float(row.get("price"), None),
                    "size": max(self._as_float(row.get("size"), 0.0), 0.0),
                    "entry_time": self._as_float(row.get("entry_time"), None),
                }
            self.open_positions = synced
            logger.info(f"RiskManager synced {len(self.open_positions)} open positions from broker")
        except Exception as e:
            logger.error(f"RiskManager sync failed: {e}")

    # =====================================================
    # CONFIG UPDATE
    # =====================================================

    def update_config(self, cfg: dict):
        self.cfg = cfg

    @staticmethod
    def _as_float(value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_symbol(symbol):
        return str(symbol or "").strip().upper()

    def _risk_cfg(self):
        risk_cfg = self.cfg.get("risk", {})
        if not isinstance(risk_cfg, dict):
            return {}
        return risk_cfg

    @staticmethod
    def _utc_day_start_epoch(now=None):
        now_ts = time.time() if now is None else float(now)
        dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
        day_start = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
        return day_start.timestamp(), day_start.date().isoformat()

    def _volatility_scaling(self, volatility):
        risk_cfg = self.cfg.get("risk", {})
        if not isinstance(risk_cfg, dict):
            risk_cfg = {}

        scaling_cfg = risk_cfg.get("volatility_scaling", {})
        if not isinstance(scaling_cfg, dict):
            scaling_cfg = {}

        enabled = scaling_cfg.get("enabled", True) is not False
        vol = self._as_float(volatility, None)
        if not enabled or vol is None or vol <= 0:
            return {
                "bucket": "base",
                "cooldown_mult": 1.0,
                "size_mult": 1.0,
            }

        low_atr = max(self._as_float(scaling_cfg.get("low_atr"), 0.003), 0.0)
        high_atr = max(
            self._as_float(scaling_cfg.get("high_atr"), 0.009),
            low_atr + 1e-9,
        )

        if vol <= low_atr:
            bucket = "low"
            cooldown_mult = self._as_float(scaling_cfg.get("low_cooldown_mult"), 1.0)
            size_mult = self._as_float(scaling_cfg.get("low_size_mult"), 1.0)
        elif vol <= high_atr:
            bucket = "medium"
            cooldown_mult = self._as_float(scaling_cfg.get("medium_cooldown_mult"), 1.25)
            size_mult = self._as_float(scaling_cfg.get("medium_size_mult"), 0.85)
        else:
            bucket = "high"
            cooldown_mult = self._as_float(scaling_cfg.get("high_cooldown_mult"), 1.6)
            size_mult = self._as_float(scaling_cfg.get("high_size_mult"), 0.65)

        max_cooldown_mult = max(
            self._as_float(scaling_cfg.get("max_cooldown_mult"), 2.5),
            1.0,
        )
        min_size_mult = min(
            max(self._as_float(scaling_cfg.get("min_size_mult"), 0.30), 0.05),
            1.0,
        )

        cooldown_mult = min(max(cooldown_mult, 1.0), max_cooldown_mult)
        size_mult = min(max(size_mult, min_size_mult), 1.0)

        return {
            "bucket": bucket,
            "cooldown_mult": cooldown_mult,
            "size_mult": size_mult,
        }

    # =====================================================
    # COOLDOWN CONTROL
    # =====================================================

    def can_trade(self, symbol, volatility=None):
        risk_cfg = self._risk_cfg()
        cooldown = float(risk_cfg.get("cooldown_seconds", 90))
        symbol_key = self._normalize_symbol(symbol)
        symbol_cooldown = risk_cfg.get("symbol_cooldown_seconds", {})
        if isinstance(symbol_cooldown, dict):
            if symbol_key in symbol_cooldown:
                cooldown = max(
                    self._as_float(symbol_cooldown.get(symbol_key), cooldown),
                    0.0,
                )
        scaling = self._volatility_scaling(volatility)
        cooldown *= scaling["cooldown_mult"]
        last_time = self.last_trade_time.get(symbol_key, 0)
        return (time.time() - last_time) >= cooldown

    def mark_trade(self, symbol):
        symbol_key = self._normalize_symbol(symbol)
        if symbol_key:
            self.last_trade_time[symbol_key] = time.time()

    def register_position(self, symbol, position: dict | None = None):
        symbol_key = self._normalize_symbol(symbol)
        if not symbol_key:
            return
        row = position if isinstance(position, dict) else {}
        self.open_positions[symbol_key] = {
            "entry": self._as_float(row.get("entry"), None),
            "size": max(self._as_float(row.get("size"), 0.0), 0.0),
            "entry_time": self._as_float(row.get("entry_time"), None),
        }

    def close_position(self, symbol):
        symbol_key = self._normalize_symbol(symbol)
        if not symbol_key:
            return
        self.open_positions.pop(symbol_key, None)

    # =====================================================
    # POSITION LIMIT CONTROL
    # =====================================================

    def can_open_position(self, current_open_positions: int):
        risk_cfg = self._risk_cfg()
        max_trades = max(int(self._as_float(risk_cfg.get("max_concurrent_trades"), 1)), 1)
        return current_open_positions < max_trades

    def can_open_position_for_symbol(self, current_symbol_positions: int):
        risk_cfg = self._risk_cfg()
        max_symbol_trades = max(
            int(self._as_float(risk_cfg.get("max_concurrent_trades_per_token"), 1)),
            1,
        )
        return current_symbol_positions < max_symbol_trades

    def can_open_under_max_trade_amount(self, current_allocated_usd: float, next_trade_cost_usd: float):
        risk_cfg = self._risk_cfg()
        raw_limit = risk_cfg.get(
            "max_trade_amount_usd",
            self._as_float(self.cfg.get("starting_balance"), None),
        )
        if raw_limit is None:
            return True

        limit = max(self._as_float(raw_limit, 0.0), 0.0)
        return (current_allocated_usd + next_trade_cost_usd) <= (limit + 1e-9)

    def exposure_block_reason(
        self,
        current_open_value_usd: float,
        current_symbol_value_usd: float,
        next_trade_cost_usd: float,
        equity_usd: float,
    ):
        if equity_usd <= 0:
            return "Equity unavailable"

        risk_cfg = self._risk_cfg()
        max_portfolio_pct = max(
            self._as_float(risk_cfg.get("max_portfolio_exposure_pct"), 100.0),
            1.0,
        )
        max_token_pct = max(
            self._as_float(risk_cfg.get("max_exposure_per_token_pct"), 100.0),
            1.0,
        )

        next_portfolio_pct = (
            (max(current_open_value_usd, 0.0) + max(next_trade_cost_usd, 0.0))
            / max(equity_usd, 1e-9)
        ) * 100.0
        if next_portfolio_pct > max_portfolio_pct:
            return (
                f"Portfolio exposure limit reached "
                f"({next_portfolio_pct:.1f}% > {max_portfolio_pct:.1f}%)"
            )

        next_token_pct = (
            (max(current_symbol_value_usd, 0.0) + max(next_trade_cost_usd, 0.0))
            / max(equity_usd, 1e-9)
        ) * 100.0
        if next_token_pct > max_token_pct:
            return (
                f"Token exposure limit reached "
                f"({next_token_pct:.1f}% > {max_token_pct:.1f}%)"
            )

        return None

    def is_within_trade_window(self, now_utc=None):
        risk_cfg = self._risk_cfg()
        window_cfg = risk_cfg.get("trade_window_utc", {})
        if not isinstance(window_cfg, dict):
            window_cfg = {}

        if window_cfg.get("enabled", False) is not True:
            return True

        start_hour = int(self._as_float(window_cfg.get("start_hour_utc"), 0) or 0)
        end_hour = int(self._as_float(window_cfg.get("end_hour_utc"), 23) or 23)
        start_hour = max(0, min(23, start_hour))
        end_hour = max(0, min(23, end_hour))

        now_dt = datetime.now(timezone.utc) if now_utc is None else now_utc
        hour = int(now_dt.hour)

        if start_hour == end_hour:
            return True
        if start_hour < end_hour:
            return start_hour <= hour < end_hour
        return hour >= start_hour or hour < end_hour

    def daily_loss_state(self, now=None):
        risk_cfg = self._risk_cfg()
        daily_loss_limit = max(
            self._as_float(risk_cfg.get("daily_loss_limit_usd"), 0.0),
            0.0,
        )
        auto_pause = bool(risk_cfg.get("daily_loss_auto_pause", True))
        close_all = bool(risk_cfg.get("daily_loss_close_all", False))

        day_start_epoch, day_key = self._utc_day_start_epoch(now=now)
        realized = 0.0
        trades_mtime = None
        trades_size = None
        if os.path.exists(TRADES_FILE):
            try:
                trades_mtime = os.path.getmtime(TRADES_FILE)
                trades_size = os.path.getsize(TRADES_FILE)
            except OSError:
                trades_mtime = None
                trades_size = None

        cache_hit = (
            self._daily_loss_cache.get("day") == day_key
            and self._daily_loss_cache.get("trades_mtime") == trades_mtime
            and self._daily_loss_cache.get("trades_size") == trades_size
        )

        if cache_hit:
            realized = self._as_float(self._daily_loss_cache.get("realized_usd"), 0.0) or 0.0
        else:
            if os.path.exists(TRADES_FILE):
                try:
                    with open(TRADES_FILE, "r", encoding="utf-8") as handle:
                        trades = json.load(handle)
                    if isinstance(trades, list):
                        for trade in trades:
                            if not isinstance(trade, dict):
                                continue
                            if str(trade.get("side", "")).upper() != "SELL":
                                continue
                            ts = self._as_float(trade.get("time"), None)
                            if ts is None or ts < day_start_epoch:
                                continue
                            pnl = self._as_float(trade.get("pnl"), 0.0) or 0.0
                            realized += pnl
                except Exception as exc:
                    logger.warning(f"Daily loss state read failed: {exc}")
            self._daily_loss_cache = {
                "day": day_key,
                "trades_mtime": trades_mtime,
                "trades_size": trades_size,
                "realized_usd": realized,
            }

        breached = daily_loss_limit > 0 and realized <= -daily_loss_limit
        return {
            "day": day_key,
            "limit_usd": daily_loss_limit,
            "realized_usd": realized,
            "breached": breached,
            "buy_paused": breached and auto_pause,
            "close_all": breached and close_all,
        }

    # =====================================================
    # POSITION SIZING
    # =====================================================

    def position_size(self, balance, entry_price, volatility=None):
        if entry_price <= 0:
            return 0.0

        risk_cfg = self.cfg.get("risk", {})
        risk_pct = float(risk_cfg.get("risk_percent", 0.02))
        trade_amount_usd = risk_cfg.get("trade_amount_usd")
        scaling = self._volatility_scaling(volatility)

        if trade_amount_usd is not None:
            trade_amount = max(float(trade_amount_usd), 0.0)
            capital_to_use = min(float(balance), trade_amount)
            sizing_mode = f"fixed_usd={trade_amount:.2f}"
        else:
            capital_to_use = max(float(balance) * risk_pct, 0.0)
            sizing_mode = f"risk_pct={risk_pct*100:.2f}%"

        capital_to_use = min(
            max(capital_to_use * scaling["size_mult"], 0.0),
            float(balance),
        )
        size = capital_to_use / float(entry_price)

        logger.info(
            f"Position sizing: balance={balance:.2f}, "
            f"{sizing_mode}, vol_bucket={scaling['bucket']}, "
            f"capital={capital_to_use:.2f}, size={size:.6f}"
        )

        return round(size, 6)
