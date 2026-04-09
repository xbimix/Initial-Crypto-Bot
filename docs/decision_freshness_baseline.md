# Decision Freshness Baseline

Generated: 2026-04-06 (UTC window end `2026-04-06T03:48:16.970853+00:00`)

## Scope
- Window: last 24h
- Data source: `.runtime/state/decision_audit.jsonl` (new schema rows only, rows containing `candle_age_seconds`)
- Decision timeframe config:
  - `market_data.decision_candle_timeframe = 1m`
  - `market_data.decision_candle_stale_intervals = 6`
  - `market_data.decision_candle_min_stale_seconds = 420`
  - Effective stale threshold: `420s`

## Baseline KPIs
- New-schema decision rows: `6150`
- Trades executed: `0`
- Blocked cycles: `6150`

Top block reasons:
1. `insufficient_data` -> `2528` (41.11%)
2. `atr_too_low` -> `990` (16.10%)
3. `market_data_quality:stale` -> `686` (11.15%)
4. `scalper_momentum_not_ready` -> `459` (7.46%)
5. `score_below_threshold` -> `422` (6.86%)

`market_data_quality:stale` age stats:
- samples: `686`
- p50: `849.48s`
- p90: `3059.51s`
- p99: `4983.53s`
- max: `6119.59s`

## Sync-State Lag Snapshot
Per-timeframe `sync_state.last_sync_ms` age (seconds):

- `1m`: p50 `13405.22`, p90 `17949.82`, max `29016.84`
- `5m`: p50 `13161.24`, p90 `17949.71`, max `28869.18`
- `15m`: p50 `13375.41`, p90 `17949.76`, max `28646.54`
- `1h`: p50 `13281.68`, p90 `18554.85`, max `349804.29`
- `4h`: p50 `13405.29`, p90 `18463.65`, max `28646.75`
- `1d`: p50 `14159.96`, p90 `18252.71`, max `29883.75`

## Interpretation
- The stale gate is mostly correct when it blocks, but the data plane is not meeting decision freshness requirements.
- The scheduler/SLO pass should be validated against this baseline before any stale-threshold tuning.
