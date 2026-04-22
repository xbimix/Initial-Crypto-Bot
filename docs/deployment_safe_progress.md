# Deployment-Safe Progress Update

This pass completed the remaining data-contract and tuning-safety scaffolding without changing strategy logic.

## 1) Candle Contract Fix + Backfill

- `close_time` is now inferred at write-time when missing:
  - `close_time = open_time + interval_ms - 1`
- A one-time runtime backfill was executed on the active DB:
  - before null close-time: `2,829,048 / 2,836,262` (`99.745651%`)
  - rows updated: `2,829,048`
  - after null close-time: `0 / 2,836,262` (`0.0%`)

Reports:
- `D:\Python-Codes\RevBot\.runtime\state\reports\candle_close_time_backfill_20260413-044411.json`
- `D:\Python-Codes\RevBot\.runtime\state\reports\candle_close_time_backfill_20260413-044411.md`

## 2) Active Threshold Contract Audit

Added runtime audit tool:
- `crypto_bot/tools/threshold_contract_audit.py`

What it checks:
- expected score/z thresholds from active config
- populated threshold fields in decision audit rows
- mismatch rates by route

Latest run reports:
- `D:\Python-Codes\RevBot\.runtime\state\reports\threshold_contract_audit_20260413-044314.json`
- `D:\Python-Codes\RevBot\.runtime\state\reports\threshold_contract_audit_20260413-044314.md`

## 3) Reversible Single-Knob Canary Tool

Added config-only canary tool:
- `crypto_bot/tools/score_threshold_experiment.py`

Safety behavior:
- applies only score-threshold keys
- snapshots baseline window
- records before/after execution/rejection/drawdown metrics
- enforces guard checks (`risk`/`profit_locks` hash unchanged)
- auto-rollback on finalize unless `--keep`

Quick usage:
- Start: `python crypto_bot/tools/score_threshold_experiment.py start --threshold 46 --hours 4`
- Status: `python crypto_bot/tools/score_threshold_experiment.py status`
- Finalize (+report): `python crypto_bot/tools/score_threshold_experiment.py finalize`
- Emergency rollback: `python crypto_bot/tools/score_threshold_experiment.py rollback`

## 4) Tests Added

- `crypto_bot/tests/test_market_data_subsystem.py`
  - `test_candle_upsert_infers_close_time_when_missing`
  - `test_backfill_null_close_times_updates_existing_rows`
- `crypto_bot/tests/test_threshold_contract_audit.py`
- `crypto_bot/tests/test_score_threshold_experiment.py`

Focused test run passed:
- `6 passed` for candle-contract + new audit/canary tests.
