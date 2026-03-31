from __future__ import annotations

import time
from pathlib import Path

from domain.contracts import FillEvent
from execution.simulator import ExecutionContext, ExecutionReport, ExecutionSimulator, OrderIntent
from utils.logger import setup_logger
from utils.state_paths import (
    read_path_with_legacy_fallback,
    resolve_legacy_state_file,
    resolve_state_dir,
    resolve_state_file,
    seed_primary_from_legacy,
)
from utils.state_storage import get_state_storage

logger = setup_logger("paper")

DEFAULT_STATE_DIR = Path(__file__).resolve().parent.parent / "state"
STATE_DIR = resolve_state_dir(DEFAULT_STATE_DIR)
BALANCE_FILE = resolve_state_file(DEFAULT_STATE_DIR, "paper_state.json")
TRADES_FILE = resolve_state_file(DEFAULT_STATE_DIR, "trades.json")
LEGACY_BALANCE_FILE = resolve_legacy_state_file(DEFAULT_STATE_DIR, "paper_state.json")
LEGACY_TRADES_FILE = resolve_legacy_state_file(DEFAULT_STATE_DIR, "trades.json")


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        if default is None:
            return None
        return float(default)


class PaperBroker:
    def __init__(self, starting_balance: float, cfg: dict | None = None):
        self.starting_balance = float(starting_balance)
        self.balance = float(starting_balance)
        self.positions: dict[str, dict] = {}
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self._state_mtime = None
        self.storage = get_state_storage()
        self.last_execution_report: dict = {}
        self.simulator = ExecutionSimulator(self._execution_cfg())

        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_balance_file()
        self._ensure_trades_file()
        self._load_state()

    def update_config(self, cfg: dict | None):
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self.simulator.update_config(self._execution_cfg())

    def _execution_cfg(self) -> dict:
        defaults = {
            "enabled": False,
            "taker_fee_bps": 12.0,
            "maker_fee_bps": 2.0,
            "base_slippage_bps": 2.0,
            "spread_slippage_weight": 0.08,
            "imbalance_penalty_bps": 8.0,
            "momentum_penalty_bps": 4.0,
            "microprice_weight": 0.35,
            "participation_penalty_bps": 4.0,
            "max_slippage_bps": 120.0,
            "soft_spread_bps": 40.0,
            "hard_reject_spread_bps": 250.0,
            "liquidity_reference_usd": 5000.0,
            "partial_fill_notional_pressure": 1.0,
            "partial_fill_slope": 0.35,
            "min_fill_ratio": 0.20,
            "reject_if_fill_ratio_below": 0.08,
            "enable_timeouts": True,
            "timeout_ms": 2200,
            "latency_pressure_ms": 450,
            "latency_slippage_bps_per_sec": 1.5,
            "maker_queue_latency_ms": 250,
            "maker_fill_decay": 0.45,
            "reject_on_bad_data": True,
        }
        raw = self.cfg.get("paper_execution", {})
        if not isinstance(raw, dict):
            return defaults
        merged = dict(defaults)
        merged.update(raw)
        merged["enabled"] = bool(merged.get("enabled", defaults["enabled"]))
        merged["enable_timeouts"] = bool(merged.get("enable_timeouts", defaults["enable_timeouts"]))
        merged["reject_on_bad_data"] = bool(merged.get("reject_on_bad_data", defaults["reject_on_bad_data"]))
        return merged

    def _ensure_balance_file(self):
        seed_primary_from_legacy(BALANCE_FILE, LEGACY_BALANCE_FILE)
        if not BALANCE_FILE.exists():
            self.storage.write(
                BALANCE_FILE,
                {"balance": self.starting_balance, "positions": {}},
            )
            self._state_mtime = self._get_state_mtime()

    def _ensure_trades_file(self):
        seed_primary_from_legacy(TRADES_FILE, LEGACY_TRADES_FILE)
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
            read_path = read_path_with_legacy_fallback(BALANCE_FILE, LEGACY_BALANCE_FILE)
            data = self.storage.read(
                read_path,
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

    def _is_maker_intent(self, trade_meta: dict | None) -> bool:
        if not isinstance(trade_meta, dict):
            return False
        role = str(trade_meta.get("liquidity_role") or trade_meta.get("execution_role") or "").strip().lower()
        return role == "maker"

    def _simulate_execution(
        self,
        *,
        side: str,
        symbol: str,
        quote_price: float,
        requested_size: float,
        trade_meta: dict | None,
    ) -> ExecutionReport:
        side_norm = "BUY" if str(side).upper() == "BUY" else "SELL"
        cfg = self._execution_cfg()
        if not cfg.get("enabled", False):
            return ExecutionReport(
                status="filled",
                side=side_norm,  # type: ignore[arg-type]
                symbol=symbol,
                quoted_price=quote_price,
                expected_fill_price=quote_price,
                effective_fill_price=quote_price,
                requested_size=requested_size,
                filled_size=requested_size,
                fill_ratio=1.0,
                fee_usd=0.0,
                slippage_bps=0.0,
                slippage_usd=0.0,
                latency_ms=0,
                latency_bucket="ideal",
                rejected=False,
                timed_out=False,
                cancelled=False,
                maker=False,
                reason=None,
            )

        intent = OrderIntent(
            side=side_norm,  # type: ignore[arg-type]
            symbol=symbol,
            quoted_price=quote_price,
            requested_size=requested_size,
            liquidity_role="maker" if self._is_maker_intent(trade_meta) else "taker",
            cancel_after_ms=(
                int(_to_float((trade_meta or {}).get("cancel_after_ms"), 0.0))
                if isinstance(trade_meta, dict) and (trade_meta or {}).get("cancel_after_ms") is not None
                else None
            ),
        )
        context = ExecutionContext.from_trade_meta(trade_meta, cfg)
        return self.simulator.simulate(intent, context)

    def _simulate_fill(
        self,
        *,
        side: str,
        symbol: str,
        quote_price: float,
        requested_size: float,
        trade_meta: dict | None,
    ) -> FillEvent:
        report = self._simulate_execution(
            side=side,
            symbol=symbol,
            quote_price=quote_price,
            requested_size=requested_size,
            trade_meta=trade_meta,
        )
        return report.to_fill_event()

    def preview_execution_cost_bps(
        self,
        *,
        side: str,
        symbol: str,
        quote_price: float,
        trade_meta: dict | None = None,
    ) -> dict:
        size_probe = max(100.0 / max(quote_price, 1e-9), 0.0001)
        report = self._simulate_execution(
            side=side,
            symbol=symbol,
            quote_price=quote_price,
            requested_size=size_probe,
            trade_meta=trade_meta,
        )
        cfg = self._execution_cfg()
        use_maker = self._is_maker_intent(trade_meta)
        fee_bps = max(_to_float(cfg.get("maker_fee_bps" if use_maker else "taker_fee_bps"), 0.0), 0.0)
        return {
            "fee_bps": fee_bps if cfg.get("enabled", False) else 0.0,
            "slippage_bps": float(report.slippage_bps),
            "total_cost_bps": (fee_bps + float(report.slippage_bps)) if cfg.get("enabled", False) else 0.0,
            "status": report.status,
            "reject_reason": report.reason,
            "expected_fill_price": report.expected_fill_price,
            "effective_fill_price": report.effective_fill_price,
        }

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
            execution = self._simulate_execution(
                side="BUY",
                symbol=symbol,
                quote_price=price,
                requested_size=size,
                trade_meta=trade_meta,
            )
            report = execution.to_dict()
            report["requested_notional_usd"] = max(price * size, 0.0)
            report["filled_notional_usd"] = max((execution.effective_fill_price or 0.0) * execution.filled_size, 0.0)
            self.last_execution_report = report

            if (
                execution.rejected
                or execution.timed_out
                or execution.cancelled
                or execution.effective_fill_price is None
                or execution.filled_size <= 0
            ):
                logger.warning(
                    f"BUY rejected for {symbol} "
                    f"status={execution.status} reason={execution.reason or 'n/a'}"
                )
                return False

            cost = (execution.effective_fill_price * execution.filled_size) + execution.fee_usd
            if cost > self.balance:
                self.last_execution_report = {
                    **report,
                    "status": "rejected",
                    "rejected": True,
                    "reason": "insufficient_balance",
                }
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
                    "stop_price",
                    "stop_distance_pct",
                    "expected_fee_bps",
                    "expected_slippage_bps",
                    "expected_total_cost_bps",
                    "sizing_mode",
                    "sizing_raw_size",
                    "sizing_capped_size",
                    "sizing_raw_notional_usd",
                    "sizing_capped_notional_usd",
                    "sizing_risk_budget_used_usd",
                    "sizing_stop_distance",
                    "sizing_per_unit_risk_usd",
                    "sizing_rejected_reason",
                    "expected_edge_bps",
                    "expected_hold_seconds",
                    "decision_ts_epoch",
                    "data_quality_status",
                    "spread_bps",
                    "spread",
                    "best_bid",
                    "best_ask",
                    "mid_price",
                    "microprice",
                    "book_imbalance",
                    "momentum_norm",
                    "atr_raw",
                    "volume_ratio",
                ):
                    value = trade_meta.get(key)
                    if value is not None:
                        entry_metadata[key] = value

            self.positions[symbol] = {
                "price": execution.effective_fill_price,
                "quoted_price": price,
                "size": execution.filled_size,
                "entry_time": float(entry_metadata.get("entry_timestamp") or time.time()),
                "reason": reason,
                "entry_fee_usd": execution.fee_usd,
                "entry_slippage_usd": execution.slippage_usd,
                **entry_metadata,
            }

            trade_row = {
                "time": time.time(),
                "symbol": symbol,
                "side": "BUY",
                "price": execution.effective_fill_price,
                "expected_fill_price": execution.expected_fill_price,
                "effective_fill_price": execution.effective_fill_price,
                "quoted_price": price,
                "size": execution.filled_size,
                "requested_size": size,
                "fill_ratio": execution.fill_ratio,
                "fill_reason": execution.reason,
                "fee_usd": execution.fee_usd,
                "slippage_bps": execution.slippage_bps,
                "slippage_usd": execution.slippage_usd,
                "latency_ms": execution.latency_ms,
                "latency_bucket": execution.latency_bucket,
                "execution_status": execution.status,
                "liquidity_role": "maker" if execution.maker else "taker",
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
                    "stop_price",
                    "stop_distance_pct",
                    "expected_fee_bps",
                    "expected_slippage_bps",
                    "expected_total_cost_bps",
                    "sizing_mode",
                    "sizing_raw_size",
                    "sizing_capped_size",
                    "sizing_raw_notional_usd",
                    "sizing_capped_notional_usd",
                    "sizing_risk_budget_used_usd",
                    "sizing_stop_distance",
                    "sizing_per_unit_risk_usd",
                    "sizing_rejected_reason",
                    "expected_edge_bps",
                    "expected_hold_seconds",
                    "decision_ts_epoch",
                    "spread_bps",
                    "microprice",
                    "book_imbalance",
                    "data_quality_status",
                ):
                    value = trade_meta.get(key)
                    if value is not None:
                        trade_row[key] = value
            self._record_trade(trade_row, use_lock=False)
            self._save_state(use_lock=False)

        logger.info(
            f"Paper BUY {symbol} @ {execution.effective_fill_price:.8f} "
            f"(quoted={price:.8f} size={execution.filled_size:.8f} "
            f"fee={execution.fee_usd:.4f} slippage_bps={execution.slippage_bps:.2f})"
        )
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
                self.last_execution_report = {
                    "status": "rejected",
                    "side": "SELL",
                    "symbol": symbol,
                    "reason": "no_open_position",
                    "position_closed": False,
                }
                logger.warning(f"SELL rejected - no open position for {symbol}")
                return False

            size = max(_to_float(pos.get("size"), 0.0), 0.0)
            entry_price = max(_to_float(pos.get("price"), 0.0), 0.0)
            entry_time = _to_float(pos.get("entry_time"), None)
            if size <= 0 or entry_price <= 0:
                self.last_execution_report = {
                    "status": "rejected",
                    "side": "SELL",
                    "symbol": symbol,
                    "reason": "invalid_position_state",
                    "position_closed": False,
                }
                logger.warning(f"SELL rejected - invalid stored position for {symbol}")
                return False

            execution = self._simulate_execution(
                side="SELL",
                symbol=symbol,
                quote_price=price,
                requested_size=size,
                trade_meta=trade_meta,
            )
            report = execution.to_dict()
            report["requested_notional_usd"] = max(price * size, 0.0)
            report["filled_notional_usd"] = max((execution.effective_fill_price or 0.0) * execution.filled_size, 0.0)

            if (
                execution.rejected
                or execution.timed_out
                or execution.cancelled
                or execution.effective_fill_price is None
                or execution.filled_size <= 0
            ):
                self.last_execution_report = report
                logger.warning(
                    f"SELL rejected for {symbol} "
                    f"status={execution.status} reason={execution.reason or 'n/a'}"
                )
                return False

            filled_size = min(execution.filled_size, size)
            remaining_size = max(size - filled_size, 0.0)
            proceeds_gross = execution.effective_fill_price * filled_size
            proceeds_net = proceeds_gross - execution.fee_usd

            entry_fee_total = max(_to_float(pos.get("entry_fee_usd"), 0.0), 0.0)
            entry_fee_for_filled = entry_fee_total * (filled_size / max(size, 1e-12))
            pnl = proceeds_net - (entry_price * filled_size) - entry_fee_for_filled

            self.balance += proceeds_net
            hold_time_seconds = None
            if entry_time is not None and entry_time > 0:
                hold_time_seconds = max(time.time() - entry_time, 0.0)

            position_closed = remaining_size <= 1e-9
            if position_closed:
                del self.positions[symbol]
            else:
                pos["size"] = remaining_size
                pos["entry_fee_usd"] = max(entry_fee_total - entry_fee_for_filled, 0.0)
                self.positions[symbol] = pos

            trade_row = {
                "time": time.time(),
                "symbol": symbol,
                "side": "SELL",
                "price": execution.effective_fill_price,
                "expected_fill_price": execution.expected_fill_price,
                "effective_fill_price": execution.effective_fill_price,
                "quoted_price": price,
                "size": filled_size,
                "requested_size": size,
                "remaining_size": remaining_size,
                "position_closed": bool(position_closed),
                "fill_ratio": execution.fill_ratio,
                "fill_reason": execution.reason,
                "fee_usd": execution.fee_usd,
                "slippage_bps": execution.slippage_bps,
                "slippage_usd": execution.slippage_usd,
                "latency_ms": execution.latency_ms,
                "latency_bucket": execution.latency_bucket,
                "execution_status": execution.status,
                "liquidity_role": "maker" if execution.maker else "taker",
                "exit_reason": reason,
                "hold_time_seconds": hold_time_seconds,
                "realized_pnl_net_usd": pnl,
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
            trade_row["entry_fee_allocated_usd"] = entry_fee_for_filled
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
                    "expected_edge_bps",
                    "expected_hold_seconds",
                    "sizing_mode",
                    "sizing_raw_size",
                    "sizing_capped_size",
                    "sizing_raw_notional_usd",
                    "sizing_capped_notional_usd",
                    "sizing_risk_budget_used_usd",
                    "sizing_stop_distance",
                    "sizing_per_unit_risk_usd",
                    "sizing_rejected_reason",
                    "decision_ts_epoch",
                    "spread_bps",
                    "microprice",
                    "book_imbalance",
                    "data_quality_status",
                ):
                    value = trade_meta.get(key)
                    if value is not None:
                        trade_row[key] = value
            self._record_trade(trade_row, use_lock=False)
            self._save_state(use_lock=False)

            self.last_execution_report = {
                **report,
                "position_closed": bool(position_closed),
                "remaining_size": remaining_size,
                "filled_size": filled_size,
                "fill_price": execution.effective_fill_price,
                "realized_pnl_usd": pnl,
                "realized_pnl_net_usd": pnl,
                "fee_usd": execution.fee_usd,
                "hold_time_seconds": hold_time_seconds,
                "exit_reason": reason,
            }

        logger.info(
            f"Paper SELL {symbol} @ {execution.effective_fill_price:.8f} "
            f"(quoted={price:.8f} size={filled_size:.8f} "
            f"fee={execution.fee_usd:.4f} pnl={pnl:.4f} closed={position_closed})"
        )
        return True
