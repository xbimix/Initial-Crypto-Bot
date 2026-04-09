# Data Pipeline Fix Plan (Phase 6)

Date: 2026-04-08  
Constraints honored:
- No strategy/routing/threshold changes
- Data pipeline only
- Backward-compatible, surgical patch

## Fix objectives

1. Improve ingestion fairness so non-decision core windows do not starve indefinitely.
2. Preserve 1m reservation behavior.
3. Keep runtime entrypoints and config compatibility stable.

## Implemented change

### Scheduler background fairness rotation

File changed:
- `crypto_bot/data/live_sync_scheduler.py`

What was happening:
- With one background slot available, selection could repeatedly choose `1h`, leaving `4h/1d` perpetually behind.
- This directly amplified `core_not_ready ... 4h:stale` / `...1d...` behavior.

What changed:
- Added background timeframe round-robin order for non-decision jobs.
- Rotation priority:
  - core first: `1h`, `4h`, `1d`
  - then secondary: `5m`, `15m`, `30m`
  - then any other present timeframe
- Rotation state persists across ticks via module-level index.
- Existing constraints preserved:
  - request cap
  - decision reservation
  - max background share
  - stale catch-up logic
  - timeframe share caps

New scheduler telemetry:
- `background_timeframe_order`
- `background_timeframe_rr_index`

## Tests added/updated

File changed:
- `crypto_bot/tests/test_live_sync_scheduler.py`

Updates:
- Reset new scheduler rr index in `setup_function`.
- Added `test_incremental_sync_scheduler_rotates_background_timeframes`:
  - verifies background slot rotates across `1h/4h/1d` instead of repeating a single core timeframe.

## Validation of implementation

- `python -m pytest -q crypto_bot/tests/test_live_sync_scheduler.py`
  - `16 passed`

## Notes

- This patch improves fairness and reduces structural starvation risk.
- Live runtime process must restart to pick up this scheduler code change.
- No strategy decision rules were changed.

