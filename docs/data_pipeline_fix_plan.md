# Data Pipeline Fix Plan (Phase 6)

Date: 2026-04-09  
Scope: data flow only (no strategy/routing/threshold rewrites)

## Constraints Honored

- No strategy route logic changes.
- No regime threshold tuning.
- No broad architecture rewrite.
- Backward-compatible defaults retained.

## Implemented Fixes

### 1) Scheduler auto-scaling controls for decision-timeframe freshness

File:
- `crypto_bot/data/live_sync_scheduler.py`

Added opt-in controls:
- `market_data.sync_auto_scale_requests_enabled` (default `False`)
- `market_data.sync_auto_scale_requests_max_per_tick` (default `12`)
- `market_data.sync_target_decision_freshness_seconds` (default `90.0`)
- `market_data.sync_assumed_tick_seconds` (default `12.0`)
- `market_data.sync_min_background_jobs_per_tick` (default `1`)

Behavior when enabled:
- Computes required decision-timeframe jobs per tick from symbol count, tick interval, and target freshness.
- Raises effective request cap up to configured max.
- Auto-reserves decision-timeframe slots while keeping a minimum background budget.

### 2) Added scheduler telemetry needed for forensic visibility

New scheduler fields:
- `request_cap_base`
- `request_cap_auto_scale_enabled`
- `request_cap_auto_scale_max`
- `request_cap_desired`
- `tick_interval_seconds`
- `target_decision_freshness_seconds`
- `decision_jobs_required_for_target`
- `min_background_jobs_per_tick`

This closes the “can’t prove why not trading” observability gap at ingestion/scheduling layer.

### 3) Added ingestion-layer guard and per-symbol update metrics

File:
- `crypto_bot/data/live_sync_scheduler.py`

New scheduler output blocks:
- `scheduler.ingestion_guard`:
  - `status` (`OK`/`DEGRADED`)
  - `reasons` (reason-code list)
  - `decision_required_jobs`
  - `decision_selected_jobs`
  - `decision_due_jobs`
  - `decision_oldest_due_age_seconds`
  - `target_decision_freshness_seconds`
- `scheduler.decision_timeframe_metrics`:
  - per symbol `last_sync_at_epoch`
  - `age_seconds`
  - observed update interval EMA
  - update frequency per hour
  - attempt/success/error counters

Reason codes currently emitted:
- `decision_timeframe_starved`
- `decision_timeframe_under_served`
- `decision_oldest_due_exceeds_target`

### 4) Config normalization support for new scheduler keys

File:
- `crypto_bot/utils/config_schema.py`

Added normalization/defaulting for all new scheduler keys to keep config migration safe.

### 5) Tests added/updated

Files:
- `crypto_bot/tests/test_live_sync_scheduler.py`
- `crypto_bot/tests/test_config_loader.py`

Coverage added:
- auto-scale cap expansion when enabled
- auto-scale disabled behavior remains stable
- ingestion guard degraded/ok states
- per-symbol decision-timeframe metrics emission
- new config defaults normalization

## Notes

- Feature is **opt-in** by default to preserve existing behavior unless explicitly enabled.
- This pass improves data-plane control without modifying strategy decisions.
