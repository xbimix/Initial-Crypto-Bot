# Data Quality Upgrade

This upgrade hardens market-data freshness and quality without requiring strategy rewrites.

## What changed

- Decision candle freshness now uses an adaptive threshold:
  - `max(decision_candle_min_stale_seconds, decision_candle_stale_intervals * candle_interval_seconds)`
- `MarketSnapshot` now includes:
  - `data_quality_score` (`0.0..1.0`)
  - `data_quality_components` (history, spread, reason penalties, core readiness)
- Strategy eval gate now supports an optional quality-score floor:
  - `market_data.strategy_eval_min_quality_score`
- Coverage and logger default paths now resolve through runtime state root (`BOT_DATA_DIR` / `REVBOT_STATE_DIR`) to avoid split-brain runtime state.

## New/normalized config keys

Under `market_data`:

- `decision_candle_timeframe`
- `decision_candle_limit`
- `decision_candle_sync_enabled`
- `decision_candle_sync_interval_seconds`
- `decision_candle_stale_intervals`
- `decision_candle_min_stale_seconds`
- `strict_strategy_eval_gate_enabled`
- `strategy_eval_max_snapshot_age_seconds`
- `strategy_eval_min_quality_score`
- `strategy_allow_partial_participation`
- `decision_context_require_quality`

## Suggested production baseline

These values are conservative and improve robustness on larger symbol universes:

```json
{
  "market_data": {
    "decision_candle_timeframe": "1m",
    "decision_candle_stale_intervals": 6,
    "decision_candle_min_stale_seconds": 420,
    "strategy_eval_min_quality_score": 0.25,
    "strategy_allow_partial_participation": true,
    "strict_strategy_eval_gate_enabled": true
  }
}
```

Tune `max_sync_requests_per_tick` and stale settings together. If sync coverage is consistently degraded, increase sync throughput before lowering quality gates.
