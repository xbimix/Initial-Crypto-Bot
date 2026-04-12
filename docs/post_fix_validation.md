# Post-Fix Validation (Phase 7)

Date: 2026-04-09

## Validation Executed

## 1) Unit tests

Commands:
- `python -m pytest -q crypto_bot/tests/test_live_sync_scheduler.py`
- `python -m pytest -q crypto_bot/tests/test_config_loader.py`
- `python -m pytest -q crypto_bot/tests/test_market_layers.py`

Results:
- `test_live_sync_scheduler.py`: **21 passed**
- `test_config_loader.py`: **17 passed**
- `test_market_layers.py`: **9 passed**

Notes:
- pytest cache warnings occurred due local Windows file-permission issues on `.pytest_cache`; tests still executed and passed.

## 2) Deterministic scheduler validation for 77-symbol workload

Scenario:
- symbols: `77`
- decision timeframe: `1m`
- base cap: `6`
- auto-scale enabled
- max cap: `14`
- target decision freshness: `90s`
- assumed tick: `12s`
- minimum background jobs: `1`

Observed scheduler output:
- `request_cap_base`: `6`
- `request_cap`: `12`
- `decision_jobs_required_for_target`: `11`
- `reserved_requests_decision_timeframe`: `11`
- `decision_selected_jobs`: `11`
- `selected_background_jobs`: `1`
- `attempted_jobs`: `12`

Implied decision refresh cadence (approx):
- `(77 symbols / 11 jobs-per-tick) * 12s` ~= **84s**

This meets the stated 60-90s target envelope for decision-candle servicing in the synthetic check.

## 3) New ingestion guard + per-symbol decision metrics validation

Added coverage verifies:
- `ingestion_guard` emits `DEGRADED` when oldest decision due age exceeds target.
- `ingestion_guard` emits `OK` when decision servicing is healthy.
- `decision_timeframe_metrics.rows` contains per-symbol:
  - `last_sync_at_epoch`
  - `age_seconds`
  - observed update interval / frequency
  - attempt/success/error counters

## 4) Live-runtime note

Live-process metrics in `.runtime/state` reflect whichever bot process is currently running.  
To validate this patch end-to-end in live runtime, restart the bot with:
- `market_data.sync_auto_scale_requests_enabled = true`
- and a suitable `sync_auto_scale_requests_max_per_tick` for your symbol set.

Then re-run 30-60 minute freshness capture and compare:
- 1m age p50/p90/max
- `% symbols >120s` and `% >300s`
- block-reason share for `core_not_ready:*stale*`
- scheduler telemetry: due/selected/starvation by timeframe

## 5) Live-runtime snapshot (last 60 minutes, current process)

Window source:
- `.runtime/state/market_sync_health_history.jsonl` (221 rows)

Observed (current running process):
- avg requests/tick: **6.0**
- avg decision due jobs: **72.045**
- avg decision selected jobs: **5.0**
- avg decision selection ratio: **0.0694**
- 1m oldest-due age p50/p90: **260.181s / 262.336s**
- ingestion stale-ratio p50/p90: **41.34% / 45.89%**
- rows carrying new scheduler fields (`request_cap_base`, `ingestion_guard`, `decision_timeframe_metrics`): **0**

Current 1m candle-age distribution (from latest DB state):
- p50/p90/max: **155.981s / 215.981s / 275.981s**
- `% >120s`: **61.039%**
- `% >300s`: **0.0%**

24h execution count from decision audit:
- executed: **0**

Interpretation:
- This process is still running pre-restart scheduler payload shape.
- Freshness improved versus older baseline but remains outside 60-90s target for most symbols.

## Conclusion

The data-plane fix is implemented and validated at unit/integration-scheduler level.  
Final operational confirmation requires a restarted live runtime window using the opt-in scheduler scaling flag so new ingestion guard/metrics are emitted in live telemetry.

---

## 6) Post-fix decision trace audit (Task 12)

Date: 2026-04-11

Command:
- `python crypto_bot/tools/decision_trace_audit.py --hours 24 --top 8`

Output summary:
- `total_cycles`: **13073**
- `trades_executed`: **0**
- `blocked_cycles`: **13073**
- `entry_blocked_cycles`: **12238**
- `exit_hold_cycles`: **835**
- Top entry blockers:
  - `price_above_buy_zone` (**46.69%** of entry-blocked cycles)
  - `price_below_buy_zone` (**18.43%**)
  - `core_not_ready:1h:stale` (**17.01%**)

Interpretation:
- The new split is working: `waiting_for_first_lock` is now isolated under `exit_hold_cycles` and no longer pollutes entry-failure diagnosis.
- Executed-opportunity rate has **not improved yet** in this live window (still 0 executions in 24h).
- Drawdown controls were not loosened in this pass; risk controls remain unchanged.

Promotion decision:
- **Do not promote tuning/profile changes yet**.
- Keep this pass as infrastructure/contract hardening and continue with a dedicated buy-zone/freshness blocker reduction pass under unchanged drawdown limits.
