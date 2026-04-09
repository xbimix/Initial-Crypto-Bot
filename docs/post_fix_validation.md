# Post-Fix Validation (Phase 7)

Date: 2026-04-08

## What was validated

1. Scheduler unit tests (including new background fairness behavior)
2. Deterministic scheduler simulation under mixed timeframe load
3. Live runtime freshness baseline (pre-restart) for comparison context

## 1) Unit tests

Command:
- `python -m pytest -q crypto_bot/tests/test_live_sync_scheduler.py`

Result:
- `16 passed`

Includes new fairness test:
- `test_incremental_sync_scheduler_rotates_background_timeframes`

## 2) Deterministic scheduler simulation

Setup:
- One symbol
- Timeframes: `1m,1h,4h,1d,5m,15m`
- Request cap: `2`
- Decision reservation: `1`
- Background share: `0.5` (one background slot)
- 30 ticks

Result:
- total calls: `60` (`30` decision + `30` background)
- background distribution:
  - `1h: 6`
  - `4h: 6`
  - `1d: 6`
  - `5m: 6`
  - `15m: 6`

Interpretation:
- Background selection now rotates evenly instead of sticking to one timeframe.

## 3) Live runtime baseline (before process restart with new code)

Recent live metrics observed:
- 1m age distribution improved from extreme stale toward moderate stale:
  - p50 around `197s`
  - p90 around `317s`
  - max around `377s`
- Scheduler starvation warnings still present in current running process logs.

Important:
- Existing bot process was started before this patch load; a restart is required for live runtime to use the new scheduler behavior.

## Validation conclusion

- Code-level fix is verified and deterministic in tests/simulation.
- Live end-to-end validation after patch requires restarting bot runtime and re-running a 30-60 minute freshness capture window.

Recommended next validation run after restart:
- Recompute:
  - 1m age p50/p90/max
  - `% symbols >120s / >300s`
  - `core_not_ready:*stale*` decision reason frequency
  - starvation timeframe counts from scheduler telemetry

