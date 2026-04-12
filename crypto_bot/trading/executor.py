from utils.logger import setup_logger
from paper.paper_broker import PaperBroker
from risk.risk_manager import RiskManager
from runtime.safety_service import RuntimeSafetyResult, RuntimeSafetyService, RuntimeSafetyState
from trading.services import (
    DecisionService,
    ExecutionService,
    PortfolioStateService,
    RiskGateService,
)
from strategy.strategy_engine import (
    clear_entry_contract,
    confirm_entry,
    confirm_exit,
    stage_entry_contract,
)

logger = setup_logger("executor")
EXECUTION_REPORT_SCHEMA_NAME = "execution_report"
EXECUTION_REPORT_SCHEMA_VERSION = 1


class Executor:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.paper = PaperBroker(cfg["starting_balance"], cfg=cfg)
        self.risk = RiskManager(cfg)
        self.decision_service = DecisionService()
        self.execution_service = ExecutionService(self.paper)
        self.portfolio = PortfolioStateService(self.paper, self.risk, logger)
        self.risk_gate = RiskGateService(self.risk, logger)
        self.last_execution_report: dict = {}
        self.runtime_safety = RuntimeSafetyService(
            cfg=self.cfg,
            risk_manager=self.risk,
            logger=logger,
        )
        self._sync_runtime_safety_compat_state()
        self._sync_risk_with_broker()

    def _ensure_services(self):
        """
        Backward-compatible lazy bootstrap for tests and legacy call sites
        that construct Executor via __new__.
        """
        if getattr(self, "decision_service", None) is None:
            self.decision_service = DecisionService()
        if getattr(self, "execution_service", None) is None:
            self.execution_service = ExecutionService(self.paper)
        if getattr(self, "portfolio", None) is None:
            self.portfolio = PortfolioStateService(self.paper, self.risk, logger)
        if getattr(self, "risk_gate", None) is None:
            self.risk_gate = RiskGateService(self.risk, logger)
        if getattr(self, "runtime_safety", None) is None:
            initial_state = RuntimeSafetyState(
                daily_loss_close_all_day=getattr(self, "_daily_loss_close_all_day", None),
                consecutive_execution_failures=int(
                    self._safe_float(getattr(self, "_consecutive_execution_failures", 0), 0) or 0
                ),
                execution_fail_pause_until=float(
                    self._safe_float(getattr(self, "_execution_fail_pause_until", 0.0), 0.0) or 0.0
                ),
                freshness_degraded_streak=int(
                    self._safe_float(getattr(self, "_freshness_degraded_streak", 0), 0) or 0
                ),
                freshness_guard_active=bool(getattr(self, "_freshness_guard_active", False)),
                freshness_block_reason=(
                    str(getattr(self, "_freshness_block_reason", "")).strip() or None
                ),
            )
            self.runtime_safety = RuntimeSafetyService(
                cfg=self.cfg,
                risk_manager=self.risk,
                logger=logger,
                initial_state=initial_state,
            )
        self._sync_runtime_safety_compat_state()

    def _sync_runtime_safety_compat_state(self):
        state = self.runtime_safety.export_state()
        self._daily_loss_close_all_day = state.daily_loss_close_all_day
        self._consecutive_execution_failures = state.consecutive_execution_failures
        self._execution_fail_pause_until = state.execution_fail_pause_until
        self._freshness_degraded_streak = state.freshness_degraded_streak
        self._freshness_guard_active = state.freshness_guard_active
        self._freshness_block_reason = state.freshness_block_reason

    # --------------------------------------------------
    # HOT RELOAD SUPPORT
    # --------------------------------------------------

    def update_config(self, cfg: dict):
        """
        Allows dynamic config reload without restarting bot.
        """
        self._ensure_services()
        self.cfg = cfg
        self.runtime_safety.update_config(cfg)
        if hasattr(self.paper, "update_config"):
            self.paper.update_config(cfg)
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
        self._ensure_services()
        return self.portfolio.has_open_position(symbol)

    def open_symbols(self) -> list[str]:
        self._ensure_services()
        return self.portfolio.open_symbols()

    def open_positions_count(self) -> int:
        self._ensure_services()
        return self.portfolio.open_positions_count()

    def _current_allocated_usd(self):
        self._ensure_services()
        return self.portfolio.current_allocated_usd()

    def enforce_daily_loss_controls(self, snapshot_fetcher=None) -> bool:
        result = self.enforce_daily_loss_controls_result(snapshot_fetcher=snapshot_fetcher)
        return bool((result.counters or {}).get("closed_positions", 0))

    def enforce_daily_loss_controls_result(self, snapshot_fetcher=None) -> RuntimeSafetyResult:
        self._ensure_services()
        result = self.runtime_safety.enforce_daily_loss_controls(
            open_symbols=self.open_symbols(),
            get_position=self.portfolio.get_position,
            execute_sell=lambda symbol, price, reason: self._handle_sell(symbol, price, reason),
            snapshot_fetcher=snapshot_fetcher if callable(snapshot_fetcher) else None,
        )
        self._sync_runtime_safety_compat_state()
        return result

    # --------------------------------------------------
    # MAIN EXECUTION ENTRY
    # --------------------------------------------------

    def handle_decision(self, decision: dict, market: dict | None = None) -> bool:
        """
        Executes strategy decision.
        Returns True if trade executed.
        Returns False otherwise.
        """
        self._ensure_services()
        context = self.decision_service.build_context(
            decision if isinstance(decision, dict) else None,
            market if isinstance(market, dict) else None,
        )
        self.last_execution_report = {}

        intent = context.intent
        symbol = intent.symbol
        action = intent.action
        price = intent.price
        reason = intent.reason

        validation_error = self.decision_service.validation_error(intent)
        if validation_error == "invalid_decision_payload":
            logger.warning(f"Invalid decision payload: {decision}")
            if action == "BUY":
                self._reject_execution(
                    side="BUY",
                    symbol=symbol or "UNKNOWN",
                    reason=validation_error,
                )
            return False
        if validation_error == "invalid_decision_price":
            logger.warning(f"Invalid decision price for {symbol}: {price}")
            if action == "BUY":
                self._reject_execution(
                    side="BUY",
                    symbol=symbol,
                    reason=validation_error,
                )
            return False

        logger.info(f"Executor: {symbol} -> {action} @ {price} | {reason}")

        if action == "BUY":
            return self._handle_buy(
                symbol,
                price,
                reason,
                context.volatility,
                context.trade_meta,
            )
        if action == "SELL":
            return self._handle_sell(symbol, price, reason, context.trade_meta)
        return False

    @staticmethod
    def _safe_float(value, default=None):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_execution_report(
        payload: dict | None,
        *,
        infer_legacy_schema: bool = False,
    ) -> dict:
        report = dict(payload) if isinstance(payload, dict) else {}
        if "schema_name" not in report:
            report["schema_name"] = EXECUTION_REPORT_SCHEMA_NAME
            if infer_legacy_schema and isinstance(payload, dict):
                report["_legacy_schema_inferred"] = True
        if "schema_version" not in report:
            report["schema_version"] = EXECUTION_REPORT_SCHEMA_VERSION
            if infer_legacy_schema and isinstance(payload, dict):
                report["_legacy_schema_inferred"] = True
        return report

    @staticmethod
    def _as_execution_report(payload: dict | None) -> dict:
        return Executor._normalize_execution_report(payload, infer_legacy_schema=False)

    @staticmethod
    def read_execution_report(payload: dict | None) -> dict:
        return Executor._normalize_execution_report(payload, infer_legacy_schema=True)

    @staticmethod
    def _normalize_buy_reject_reason(reason: str | None) -> str:
        token = str(reason or "").strip().lower()
        if not token:
            return "buy_rejected"
        aliases = {
            "liquidity_score_below_floor": "liquidity_floor",
        }
        return aliases.get(token, token)

    def _reject_execution(
        self,
        *,
        side: str,
        symbol: str,
        reason: str | None,
        extra: dict | None = None,
    ) -> bool:
        payload = {
            "status": "rejected",
            "reason": str(reason or "execution_rejected"),
            "side": str(side or "").upper(),
            "symbol": symbol,
        }
        if isinstance(extra, dict):
            payload.update(extra)
        self.last_execution_report = self._as_execution_report(payload)
        return False

    def _estimate_stop_price(
        self,
        *,
        price: float,
        volatility,
        route: str | None,
        atr_raw,
    ) -> tuple[float | None, float | None]:
        vol = self._safe_float(atr_raw, None)
        if vol is None:
            vol = self._safe_float(volatility, None)
        if vol is None or vol <= 0:
            return None, None

        risk_cfg = self.cfg.get("risk", {})
        if not isinstance(risk_cfg, dict):
            risk_cfg = {}
        stop_mult_default = max(self._safe_float(risk_cfg.get("stop_atr_mult_default"), 1.4) or 1.4, 0.1)
        route_key = str(route or "").strip().lower()
        route_mult = stop_mult_default
        if route_key == "trend_pullback":
            route_mult = max(self._safe_float(risk_cfg.get("stop_atr_mult_trend"), 2.0) or 2.0, 0.1)
        elif route_key == "breakout_momentum":
            route_mult = max(self._safe_float(risk_cfg.get("stop_atr_mult_breakout"), 1.7) or 1.7, 0.1)
        elif route_key == "mean_reversion":
            route_mult = max(self._safe_float(risk_cfg.get("stop_atr_mult_mean_reversion"), 1.1) or 1.1, 0.1)
        stop_distance_pct = max(vol * route_mult, 0.001)
        stop_price = max(price * (1.0 - stop_distance_pct), 0.0)
        return stop_price, stop_distance_pct

    def _estimate_liquidity_score(self, trade_meta: dict | None) -> float | None:
        if not isinstance(trade_meta, dict):
            return None
        volume_ratio = self._safe_float(trade_meta.get("volume_ratio"), None)
        spread_bps = self._safe_float(trade_meta.get("spread_bps"), None)
        score = None
        if volume_ratio is not None:
            score = max(min(volume_ratio, 2.0), 0.0) / 2.0
        if spread_bps is not None and spread_bps >= 0:
            spread_score = max(0.0, 1.0 - min(spread_bps / 200.0, 1.0))
            score = spread_score if score is None else min(score, spread_score)
        return score

    def _sync_risk_with_broker(self):
        """
        Keep RiskManager in sync with restored broker positions when supported.
        """
        self._ensure_services()
        self.portfolio.sync_risk_with_broker()

    def _execution_failure_limits(self) -> tuple[int, int]:
        self._ensure_services()
        return self.runtime_safety.failure_limits()

    def _register_execution_success(self):
        self._ensure_services()
        self.runtime_safety.record_execution_success()
        self._sync_runtime_safety_compat_state()

    def _register_execution_failure(self, reason: str | None = None):
        self._ensure_services()
        self.runtime_safety.record_execution_failure(reason=reason)
        self._sync_runtime_safety_compat_state()

    def record_freshness_slo(self, slo: dict | None) -> RuntimeSafetyResult:
        self._ensure_services()
        result = self.runtime_safety.record_freshness_slo(slo if isinstance(slo, dict) else {})
        self._sync_runtime_safety_compat_state()
        return result

    # --------------------------------------------------
    # BUY HANDLER
    # --------------------------------------------------

    def _handle_buy(
        self,
        symbol: str,
        price: float,
        reason: str,
        volatility=None,
        trade_meta: dict | None = None,
    ) -> bool:
        self._ensure_services()
        staged = isinstance(trade_meta, dict)
        if staged:
            stage_entry_contract(symbol, trade_meta)
        executed = False

        try:
            runtime_safety = self.runtime_safety.check_buy_allowed(symbol)
            if not runtime_safety.allowed:
                return self._reject_execution(
                    side="BUY",
                    symbol=symbol,
                    reason=runtime_safety.blocked_reason or "runtime_safety_blocked",
                    extra={
                        "runtime_safety_counters": dict(runtime_safety.counters or {}),
                        "runtime_safety_thresholds": dict(runtime_safety.thresholds or {}),
                    },
                )

            has_position = self.has_open_position(symbol)
            precondition_reason = self.risk_gate.check_buy_preconditions(
                cfg=self.cfg,
                symbol=symbol,
                volatility=volatility,
                trade_meta=trade_meta,
                open_positions_count=self.open_positions_count(),
                symbol_open_positions=1 if has_position else 0,
                has_open_position=has_position,
            )
            if precondition_reason:
                return self._reject_execution(
                    side="BUY",
                    symbol=symbol,
                    reason=self._normalize_buy_reject_reason(precondition_reason),
                )

            balance = self.paper.get_balance()
            route = None
            if isinstance(trade_meta, dict):
                route = trade_meta.get("entry_route") or trade_meta.get("effective_route")
            stop_price, stop_distance_pct = self._estimate_stop_price(
                price=price,
                volatility=volatility,
                route=route,
                atr_raw=(trade_meta or {}).get("atr_raw"),
            )
            preview = self.paper.preview_execution_cost_bps(
                side="BUY",
                symbol=symbol,
                quote_price=price,
                trade_meta=trade_meta,
            )
            expected_fee_bps = self._safe_float(preview.get("fee_bps"), 0.0) or 0.0
            expected_slippage_bps = self._safe_float(preview.get("slippage_bps"), 0.0) or 0.0
            expected_total_cost_bps = self._safe_float(preview.get("total_cost_bps"), 0.0) or 0.0
            liquidity_score = self._estimate_liquidity_score(trade_meta)
            if isinstance(trade_meta, dict):
                trade_meta["stop_price"] = stop_price
                trade_meta["stop_distance_pct"] = stop_distance_pct
                trade_meta["expected_fee_bps"] = expected_fee_bps
                trade_meta["expected_slippage_bps"] = expected_slippage_bps
                trade_meta["expected_total_cost_bps"] = expected_total_cost_bps

            current_allocated, per_symbol_allocated = self._current_allocated_usd()
            current_symbol_allocated = per_symbol_allocated.get(symbol, 0.0)
            equity = max(balance, 0.0) + max(current_allocated, 0.0)

            sizing_result = self.risk.position_sizing(
                balance,
                price,
                volatility=volatility,
                stop_price=stop_price,
                expected_fee_bps=expected_fee_bps,
                expected_slippage_bps=expected_slippage_bps,
                spread_bps=(trade_meta or {}).get("spread_bps"),
                liquidity_score=liquidity_score,
                current_open_value_usd=current_allocated,
                current_symbol_value_usd=current_symbol_allocated,
                equity_usd=equity,
            )
            size = float(sizing_result.capped_size)
            if isinstance(trade_meta, dict):
                trade_meta["sizing_mode"] = sizing_result.mode
                trade_meta["sizing_raw_size"] = sizing_result.raw_size
                trade_meta["sizing_capped_size"] = sizing_result.capped_size
                trade_meta["sizing_raw_notional_usd"] = sizing_result.raw_notional_usd
                trade_meta["sizing_capped_notional_usd"] = sizing_result.capped_notional_usd
                trade_meta["sizing_risk_budget_used_usd"] = sizing_result.risk_budget_used_usd
                trade_meta["sizing_stop_distance"] = sizing_result.stop_distance
                trade_meta["sizing_per_unit_risk_usd"] = sizing_result.per_unit_risk_usd
                trade_meta["sizing_rejected_reason"] = sizing_result.rejected_reason

            if size <= 0:
                reject_reason = self._normalize_buy_reject_reason(sizing_result.rejected_reason or "size_capped_to_zero")
                logger.warning(
                    f"Invalid position size for {symbol} "
                    f"(reason={sizing_result.rejected_reason or 'unknown'})"
                )
                return self._reject_execution(
                    side="BUY",
                    symbol=symbol,
                    reason=reject_reason,
                    extra={
                        "sizing_rejected_reason": sizing_result.rejected_reason,
                        "sizing_mode": sizing_result.mode,
                    },
                )

            expected_cost_multiplier = 1.0 + (expected_total_cost_bps / 10000.0)
            trade_cost = price * size * expected_cost_multiplier
            max_trade_headroom = None
            if hasattr(self.risk, "max_trade_amount_headroom_usd"):
                max_trade_headroom = self.risk.max_trade_amount_headroom_usd(current_allocated)
            if max_trade_headroom is not None:
                if max_trade_headroom <= 0:
                    return self._reject_execution(
                        side="BUY",
                        symbol=symbol,
                        reason="max_trade_amount",
                        extra={
                            "max_trade_headroom_usd": 0.0,
                            "current_allocated_usd": current_allocated,
                        },
                    )
                if trade_cost > (max_trade_headroom + 1e-9):
                    unit_cost = max(price * expected_cost_multiplier, 1e-9)
                    clipped_size = max(max_trade_headroom / unit_cost, 0.0)
                    if clipped_size < size:
                        size = clipped_size
                        trade_cost = price * size * expected_cost_multiplier
                        if isinstance(trade_meta, dict):
                            trade_meta["sizing_headroom_clip_applied"] = True
                            trade_meta["sizing_headroom_clip_usd"] = max_trade_headroom
                            trade_meta["sizing_capped_size"] = size
                            trade_meta["sizing_capped_notional_usd"] = size * price
            min_trade_notional = self._safe_float(getattr(sizing_result, "min_trade_notional_usd", None), None)
            if min_trade_notional is not None and trade_cost < min_trade_notional:
                return self._reject_execution(
                    side="BUY",
                    symbol=symbol,
                    reason="below_min_trade_notional",
                    extra={
                        "trade_cost_usd": trade_cost,
                        "min_trade_notional_usd": min_trade_notional,
                    },
                )

            allocation_reason = self.risk_gate.check_allocation_limits(
                symbol=symbol,
                trade_cost=trade_cost,
                current_allocated=current_allocated,
                current_symbol_allocated=current_symbol_allocated,
                equity=equity,
            )
            if allocation_reason:
                return self._reject_execution(
                    side="BUY",
                    symbol=symbol,
                    reason=self._normalize_buy_reject_reason(allocation_reason),
                )

            ok, execution_report = self.execution_service.execute_buy(
                symbol=symbol,
                price=price,
                size=size,
                reason=reason,
                trade_meta=trade_meta,
            )
            self.last_execution_report = self._as_execution_report(execution_report)
            if ok:
                fill_price, _fill_size = self.portfolio.register_buy_fill(
                    symbol=symbol,
                    fallback_price=price,
                    fallback_size=size,
                )
                meta = trade_meta if isinstance(trade_meta, dict) else {}
                confirm_entry(
                    symbol,
                    fill_price,
                    entry_route=meta.get("entry_route"),
                    entry_regime=meta.get("entry_regime"),
                    exit_policy=meta.get("exit_policy"),
                    entry_confidence=meta.get("entry_confidence"),
                    entry_timestamp=meta.get("entry_timestamp"),
                    route_eval_ts=meta.get("route_eval_ts"),
                    regime_eval_ts=meta.get("regime_eval_ts"),
                )
                executed = True
                self._register_execution_success()
                return True

            failure_reason = str(self.last_execution_report.get("reason") or "buy_failed")
            failure_status = str(self.last_execution_report.get("status") or "").strip().lower()
            normalized_report = (
                dict(self.last_execution_report)
                if isinstance(self.last_execution_report, dict)
                else {}
            )
            normalized_report["status"] = "rejected"
            normalized_report["reason"] = failure_reason
            normalized_report["side"] = "BUY"
            normalized_report["symbol"] = symbol
            if failure_status and failure_status != "rejected":
                normalized_report["execution_status"] = failure_status
            self.last_execution_report = self._as_execution_report(normalized_report)
            self._register_execution_failure(failure_reason)
            return False
        finally:
            if staged and not executed:
                clear_entry_contract(symbol)

    # --------------------------------------------------
    # SELL HANDLER
    # --------------------------------------------------

    def _handle_sell(
        self,
        symbol: str,
        price: float,
        reason: str,
        trade_meta: dict | None = None,
    ) -> bool:
        self._ensure_services()
        if not self.has_open_position(symbol):
            logger.warning(f"No open position to sell for {symbol}")
            confirm_exit(symbol, price)
            self.last_execution_report = self._as_execution_report({
                "status": "rejected",
                "reason": "no_open_position",
                "side": "SELL",
                "symbol": symbol,
            })
            return False

        position = self.portfolio.get_position(symbol) or {}
        sell_trade_meta = self.decision_service.enrich_sell_trade_meta(position, trade_meta)

        ok, execution_report = self.execution_service.execute_sell(
            symbol=symbol,
            price=price,
            reason=reason,
            trade_meta=sell_trade_meta,
        )
        self.last_execution_report = self._as_execution_report(execution_report)
        if ok:
            position_closed = self.portfolio.register_sell_fill(
                symbol=symbol,
                execution_report=self.last_execution_report,
            )
            if position_closed:
                fill_price = self._safe_float(self.last_execution_report.get("fill_price"), price) or price
                confirm_exit(symbol, fill_price)
            self._register_execution_success()
            return True

        self._register_execution_failure(str(self.last_execution_report.get("reason") or "sell_failed"))
        return False
