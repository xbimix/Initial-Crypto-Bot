# Implementation Checklist: Revised Priority Order

Audit date: 2026-04-06  
Scope: verify whether the revised priority list was converted into a checklist and executed.

## P0
- [x] Decouple ingestion vs decision universes
  - Evidence: `main.py` uses `sync_symbol_scope` + `sync_symbols_for_tick`; scheduler owns symbol-scope resolution.
  - Files: `crypto_bot/main.py`, `crypto_bot/runtime/market_cycle_scheduler.py`, `crypto_bot/utils/config_schema.py`
- [x] Guarantee 1m reservation across ingestion universe
  - Evidence: reserved request budget for decision timeframe and enforcement metrics (`reserved_requests_decision_timeframe`, `decision_reservation_met`).
  - Files: `crypto_bot/data/live_sync_scheduler.py`, `crypto_bot/utils/config_schema.py`
- [x] Freshness ledger (per symbol/timeframe)
  - Evidence: ingestion freshness ledger persisted to current state root, with per symbol/timeframe age + stale flags.
  - Files: `crypto_bot/main.py`, `crypto_bot/data/revolut_market_db.py`, `crypto_bot/data/revolut_candle_store.py`
- [x] Fix config path visibility
  - Evidence: runtime state root resolution through `BOT_DATA_DIR`/`REVBOT_STATE_DIR`; logger/coverage/control use state path helpers.
  - Files: `crypto_bot/utils/state_paths.py`, `crypto_bot/utils/logger.py`, `crypto_bot/control/control_server.py`, `crypto_bot/data/candle_coverage.py`

## P0.5
- [x] Catch-up priority for stale symbols
  - Evidence: explicit stale-symbol catch-up controls now exist in runtime symbol scope and incremental scheduler (`sync_stale_catchup_enabled`, age-interval threshold, reserved catch-up requests, max symbol cap).
  - Files: `crypto_bot/runtime/market_cycle_scheduler.py`, `crypto_bot/data/live_sync_scheduler.py`, `crypto_bot/main.py`, `crypto_bot/utils/config_schema.py`

## P1
- [x] Background TF scheduling ceilings
  - Evidence: `sync_max_background_share`, `sync_timeframe_max_share`, per-timeframe caps and starvation telemetry.
  - File: `crypto_bot/data/live_sync_scheduler.py`
- [x] Trade tape handling correction
  - Evidence: explicit global-tape semantics, symbol-safe filtering in ingestion, and sparse-symbol guard tests.
  - Files: `crypto_bot/api/revolut_trades.py`, `crypto_bot/data/ingestion.py`, `crypto_bot/tests/test_market_layers.py`
- [x] Advisory vs execution separation
  - Evidence: decision-input gate/context and dedicated execution service path.
  - Files: `crypto_bot/data/decision_input_builder.py`, `crypto_bot/trading/services/execution_service.py`, `crypto_bot/trading/executor.py`
- [x] Endpoint optimization
  - Evidence: endpoint capability cache, TTL/cooldown, working-candidate reuse, variant fallback policy.
  - File: `crypto_bot/data/revolut_candle_fetcher.py`

## P2
- [x] ATR robustness
  - Evidence: non-zero returns median for ATR raw; regression test included.
  - Files: `crypto_bot/data/feature_engine.py`, `crypto_bot/tests/test_market_layers.py`
- [x] Replay validation
  - Evidence: replay integration + persistence + strategy replay fixture tests present and passing.
  - Files: `crypto_bot/tests/test_replay_integration_suite.py`, `crypto_bot/tests/test_replay_persistence.py`, `crypto_bot/tests/test_strategy_replay_fixture.py`
- [ ] Threshold tuning
  - Status: tooling exists, but no confirmed closed-loop execution of tuning pass in this checklist.
  - Files: `crypto_bot/tools/profit_profile_rollout.py`, `crypto_bot/tools/profit_profile_verify.py`, `crypto_bot/tools/regime_confidence_recalibration_report.py`

## Verification Run (this audit)
- Ran:
  - `pytest crypto_bot/tests/test_replay_integration_suite.py crypto_bot/tests/test_replay_persistence.py crypto_bot/tests/test_strategy_replay_fixture.py -q`
- Result:
  - `6 passed`
