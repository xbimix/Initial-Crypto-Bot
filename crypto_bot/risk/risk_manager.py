import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from utils.logger import setup_logger
from utils.state_paths import (
    read_path_with_legacy_fallback,
    resolve_legacy_state_file,
    resolve_state_file,
    seed_primary_from_legacy,
)

logger = setup_logger("risk")

DEFAULT_STATE_DIR = Path(__file__).resolve().parent.parent / "state"
PAPER_STATE_FILE = resolve_state_file(DEFAULT_STATE_DIR, "paper_state.json")
TRADES_FILE = resolve_state_file(DEFAULT_STATE_DIR, "trades.json")
LEGACY_PAPER_STATE_FILE = resolve_legacy_state_file(DEFAULT_STATE_DIR, "paper_state.json")
LEGACY_TRADES_FILE = resolve_legacy_state_file(DEFAULT_STATE_DIR, "trades.json")


@dataclass(frozen=True)
class PositionSizingResult:
    mode: str
    raw_size: float
    capped_size: float
    risk_budget_used_usd: float
    stop_distance: float | None
    per_unit_risk_usd: float | None
    expected_fee_bps: float
    expected_slippage_bps: float
    expected_total_cost_bps: float
    min_trade_notional_usd: float
    raw_notional_usd: float
    capped_notional_usd: float
    rejected_reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


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
        seed_primary_from_legacy(PAPER_STATE_FILE, LEGACY_PAPER_STATE_FILE)
        read_path = read_path_with_legacy_fallback(
            PAPER_STATE_FILE,
            LEGACY_PAPER_STATE_FILE,
            context="risk_manager.sync_paper_state",
        )
        if not read_path.exists():
            self.open_positions = {}
            return

        try:
            with open(read_path, "r", encoding="utf-8") as f:
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
        seed_primary_from_legacy(TRADES_FILE, LEGACY_TRADES_FILE)
        trades_path = read_path_with_legacy_fallback(
            TRADES_FILE,
            LEGACY_TRADES_FILE,
            context="risk_manager.daily_loss_state",
        )
        if trades_path.exists():
            try:
                trades_mtime = os.path.getmtime(trades_path)
                trades_size = os.path.getsize(trades_path)
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
            if trades_path.exists():
                try:
                    with open(trades_path, "r", encoding="utf-8") as handle:
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

    def _risk_sizing_mode(self) -> str:
        risk_cfg = self._risk_cfg()
        mode = str(risk_cfg.get("sizing_mode", "auto") or "").strip().lower()
        allowed = {"auto", "stop_distance", "fixed_usd", "risk_percent"}
        if mode not in allowed:
            return "auto"
        return mode

    def _risk_budget_usd(self, balance: float) -> float:
        risk_cfg = self._risk_cfg()
        risk_pct = max(self._as_float(risk_cfg.get("risk_percent"), 0.02), 0.0)
        budget = max(float(balance) * risk_pct, 0.0)
        explicit_budget = self._as_float(risk_cfg.get("max_loss_per_trade_usd"), None)
        if explicit_budget is not None and explicit_budget >= 0:
            budget = min(budget, explicit_budget) if budget > 0 else explicit_budget
        return max(budget, 0.0)

    def position_sizing(
        self,
        balance,
        entry_price,
        volatility=None,
        *,
        stop_price=None,
        expected_fee_bps=None,
        expected_slippage_bps=None,
        spread_bps=None,
        liquidity_score=None,
        current_open_value_usd: float = 0.0,
        current_symbol_value_usd: float = 0.0,
        equity_usd: float | None = None,
    ) -> PositionSizingResult:
        if entry_price <= 0:
            return PositionSizingResult(
                mode="invalid",
                raw_size=0.0,
                capped_size=0.0,
                risk_budget_used_usd=0.0,
                stop_distance=None,
                per_unit_risk_usd=None,
                expected_fee_bps=0.0,
                expected_slippage_bps=0.0,
                expected_total_cost_bps=0.0,
                min_trade_notional_usd=0.0,
                raw_notional_usd=0.0,
                capped_notional_usd=0.0,
                rejected_reason="invalid_entry_price",
            )

        risk_cfg = self._risk_cfg()
        risk_pct = float(risk_cfg.get("risk_percent", 0.02))
        trade_amount_usd = risk_cfg.get("trade_amount_usd")
        scaling = self._volatility_scaling(volatility)
        expected_fee_bps = max(self._as_float(expected_fee_bps, 0.0), 0.0)
        expected_slippage_bps = max(self._as_float(expected_slippage_bps, 0.0), 0.0)
        expected_cost_pct = (expected_fee_bps + expected_slippage_bps) / 10000.0
        spread_bps = self._as_float(spread_bps, None)
        liquidity_score = self._as_float(liquidity_score, None)

        sizing_mode = self._risk_sizing_mode()

        if sizing_mode == "fixed_usd" and trade_amount_usd is None:
            return PositionSizingResult(
                mode=sizing_mode,
                raw_size=0.0,
                capped_size=0.0,
                risk_budget_used_usd=0.0,
                stop_distance=None,
                per_unit_risk_usd=None,
                expected_fee_bps=expected_fee_bps,
                expected_slippage_bps=expected_slippage_bps,
                expected_total_cost_bps=(expected_fee_bps + expected_slippage_bps),
                min_trade_notional_usd=0.0,
                raw_notional_usd=0.0,
                capped_notional_usd=0.0,
                rejected_reason="trade_amount_usd_required",
            )

        legacy_fixed_usd = trade_amount_usd is not None and sizing_mode == "auto"
        if sizing_mode == "fixed_usd" or legacy_fixed_usd:
            trade_amount = max(float(trade_amount_usd), 0.0)
            capital_to_use = min(float(balance), trade_amount)
            mode_used = "fixed_usd"
        elif sizing_mode == "risk_percent":
            capital_to_use = max(float(balance) * risk_pct, 0.0)
            mode_used = "risk_percent"
        else:
            capital_to_use = (
                min(float(balance), max(float(trade_amount_usd), 0.0))
                if trade_amount_usd is not None
                else max(float(balance) * risk_pct, 0.0)
            )
            mode_used = "stop_distance"

        capital_to_use = min(
            max(capital_to_use * scaling["size_mult"], 0.0),
            float(balance),
        )
        size_by_capital = capital_to_use / float(entry_price)

        size = size_by_capital
        stop_distance = None
        per_unit_risk = None
        risk_budget_usd = self._risk_budget_usd(float(balance))
        stop = self._as_float(stop_price, None)
        if stop is not None and stop > 0:
            stop_distance = max(float(entry_price) - float(stop), 0.0)
            if stop_distance > 0:
                per_unit_risk = stop_distance + (float(entry_price) * expected_cost_pct)
                if per_unit_risk > 0:
                    size_by_stop = max(risk_budget_usd / per_unit_risk, 0.0)
                    size = min(size_by_capital, size_by_stop)
        elif mode_used == "stop_distance":
            return PositionSizingResult(
                mode=mode_used,
                raw_size=0.0,
                capped_size=0.0,
                risk_budget_used_usd=risk_budget_usd,
                stop_distance=None,
                per_unit_risk_usd=None,
                expected_fee_bps=expected_fee_bps,
                expected_slippage_bps=expected_slippage_bps,
                expected_total_cost_bps=(expected_fee_bps + expected_slippage_bps),
                min_trade_notional_usd=max(self._as_float(risk_cfg.get("min_trade_notional_usd"), 10.0), 0.0),
                raw_notional_usd=0.0,
                capped_notional_usd=0.0,
                rejected_reason="missing_or_invalid_stop",
            )

        # Liquidity-aware scaling keeps size conservative on hostile tape.
        if spread_bps is not None and spread_bps >= 0:
            soft_spread_bps = max(self._as_float(risk_cfg.get("liquidity_soft_spread_bps"), 45.0), 1.0)
            hard_spread_bps = max(self._as_float(risk_cfg.get("liquidity_hard_spread_bps"), 220.0), soft_spread_bps)
            if spread_bps >= hard_spread_bps:
                logger.info(
                    f"Position sizing blocked by hard spread cap: spread_bps={spread_bps:.2f} "
                    f"hard_spread_bps={hard_spread_bps:.2f}"
                )
                return PositionSizingResult(
                    mode=mode_used,
                    raw_size=0.0,
                    capped_size=0.0,
                    risk_budget_used_usd=risk_budget_usd,
                    stop_distance=stop_distance,
                    per_unit_risk_usd=per_unit_risk,
                    expected_fee_bps=expected_fee_bps,
                    expected_slippage_bps=expected_slippage_bps,
                    expected_total_cost_bps=(expected_fee_bps + expected_slippage_bps),
                    min_trade_notional_usd=max(self._as_float(risk_cfg.get("min_trade_notional_usd"), 10.0), 0.0),
                    raw_notional_usd=0.0,
                    capped_notional_usd=0.0,
                    rejected_reason="spread_hard_cap",
                )
            if spread_bps > soft_spread_bps:
                spread_scale = max(min(soft_spread_bps / spread_bps, 1.0), 0.25)
                size *= spread_scale

        if liquidity_score is not None:
            liquidity_floor = _clamp(self._as_float(risk_cfg.get("liquidity_score_floor"), 0.15), 0.0, 1.0)
            if liquidity_score < liquidity_floor:
                logger.info(
                    f"Position sizing blocked by liquidity score: score={liquidity_score:.3f} "
                    f"floor={liquidity_floor:.3f}"
                )
                return PositionSizingResult(
                    mode=mode_used,
                    raw_size=0.0,
                    capped_size=0.0,
                    risk_budget_used_usd=risk_budget_usd,
                    stop_distance=stop_distance,
                    per_unit_risk_usd=per_unit_risk,
                    expected_fee_bps=expected_fee_bps,
                    expected_slippage_bps=expected_slippage_bps,
                    expected_total_cost_bps=(expected_fee_bps + expected_slippage_bps),
                    min_trade_notional_usd=max(self._as_float(risk_cfg.get("min_trade_notional_usd"), 10.0), 0.0),
                    raw_notional_usd=0.0,
                    capped_notional_usd=0.0,
                    rejected_reason="liquidity_score_below_floor",
                )
            if liquidity_score < 0.8:
                # Scale down gradually in thin conditions.
                size *= max(liquidity_score / 0.8, 0.35)

        raw_size = max(size, 0.0)
        raw_notional = raw_size * float(entry_price)
        capped_notional = raw_notional

        max_notional_usd = self._as_float(risk_cfg.get("max_notional_usd"), None)
        if max_notional_usd is not None and max_notional_usd >= 0:
            capped_notional = min(capped_notional, max_notional_usd)

        effective_equity = self._as_float(equity_usd, None)
        if effective_equity is None or effective_equity <= 0:
            effective_equity = max(float(balance), 0.0) + max(self._as_float(current_open_value_usd, 0.0), 0.0)
        if effective_equity > 0:
            max_portfolio_pct = max(self._as_float(risk_cfg.get("max_portfolio_exposure_pct"), 100.0), 1.0)
            max_symbol_pct = max(self._as_float(risk_cfg.get("max_exposure_per_token_pct"), 100.0), 1.0)
            portfolio_cap_notional = max((effective_equity * (max_portfolio_pct / 100.0)) - max(current_open_value_usd, 0.0), 0.0)
            symbol_cap_notional = max((effective_equity * (max_symbol_pct / 100.0)) - max(current_symbol_value_usd, 0.0), 0.0)
            capped_notional = min(capped_notional, portfolio_cap_notional, symbol_cap_notional)

        liquidity_cap_notional = self._as_float(risk_cfg.get("liquidity_cap_notional_usd"), None)
        if liquidity_cap_notional is not None and liquidity_cap_notional >= 0:
            if liquidity_score is not None:
                capped_notional = min(capped_notional, liquidity_cap_notional * max(liquidity_score, 0.1))
            else:
                capped_notional = min(capped_notional, liquidity_cap_notional)

        min_trade_notional_usd = max(self._as_float(risk_cfg.get("min_trade_notional_usd"), 10.0), 0.0)
        if capped_notional < min_trade_notional_usd:
            return PositionSizingResult(
                mode=mode_used,
                raw_size=raw_size,
                capped_size=0.0,
                risk_budget_used_usd=risk_budget_usd,
                stop_distance=stop_distance,
                per_unit_risk_usd=per_unit_risk,
                expected_fee_bps=expected_fee_bps,
                expected_slippage_bps=expected_slippage_bps,
                expected_total_cost_bps=(expected_fee_bps + expected_slippage_bps),
                min_trade_notional_usd=min_trade_notional_usd,
                raw_notional_usd=raw_notional,
                capped_notional_usd=max(capped_notional, 0.0),
                rejected_reason="below_min_trade_notional",
            )

        capped_size = max(capped_notional / max(float(entry_price), 1e-9), 0.0)
        if capped_size <= 0:
            return PositionSizingResult(
                mode=mode_used,
                raw_size=raw_size,
                capped_size=0.0,
                risk_budget_used_usd=risk_budget_usd,
                stop_distance=stop_distance,
                per_unit_risk_usd=per_unit_risk,
                expected_fee_bps=expected_fee_bps,
                expected_slippage_bps=expected_slippage_bps,
                expected_total_cost_bps=(expected_fee_bps + expected_slippage_bps),
                min_trade_notional_usd=min_trade_notional_usd,
                raw_notional_usd=raw_notional,
                capped_notional_usd=max(capped_notional, 0.0),
                rejected_reason="size_capped_to_zero",
            )

        logger.info(
            f"Position sizing: balance={balance:.2f}, mode={mode_used}, vol_bucket={scaling['bucket']}, "
            f"capital={capital_to_use:.2f}, stop={stop}, stop_dist={stop_distance}, "
            f"risk_budget={risk_budget_usd:.2f}, per_unit_risk={per_unit_risk}, "
            f"cost_bps={(expected_fee_bps + expected_slippage_bps):.2f}, spread_bps={spread_bps}, "
            f"liquidity_score={liquidity_score}, raw_size={raw_size:.6f}, capped_size={capped_size:.6f}"
        )

        return PositionSizingResult(
            mode=mode_used,
            raw_size=round(raw_size, 6),
            capped_size=round(capped_size, 6),
            risk_budget_used_usd=round(risk_budget_usd, 6),
            stop_distance=(round(stop_distance, 8) if stop_distance is not None else None),
            per_unit_risk_usd=(round(per_unit_risk, 8) if per_unit_risk is not None else None),
            expected_fee_bps=round(expected_fee_bps, 6),
            expected_slippage_bps=round(expected_slippage_bps, 6),
            expected_total_cost_bps=round(expected_fee_bps + expected_slippage_bps, 6),
            min_trade_notional_usd=round(min_trade_notional_usd, 6),
            raw_notional_usd=round(raw_notional, 6),
            capped_notional_usd=round(capped_notional, 6),
            rejected_reason=None,
        )

    def position_size(
        self,
        balance,
        entry_price,
        volatility=None,
        *,
        stop_price=None,
        expected_fee_bps=None,
        expected_slippage_bps=None,
        spread_bps=None,
        liquidity_score=None,
    ):
        result = self.position_sizing(
            balance,
            entry_price,
            volatility=volatility,
            stop_price=stop_price,
            expected_fee_bps=expected_fee_bps,
            expected_slippage_bps=expected_slippage_bps,
            spread_bps=spread_bps,
            liquidity_score=liquidity_score,
        )
        return round(result.capped_size, 6)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
