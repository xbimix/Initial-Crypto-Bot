# Data Freshness Report (Phase 2)

Date: 2026-04-09 (UTC)
Scope: Freshness validation only (no strategy/routing/threshold changes)
Runtime root: `.runtime/state/`

## Method

1. Computed per-symbol 1m candle freshness from SQLite:
- source: `.runtime/state/market_data.db` (`candles` table)
- `candle_age_seconds = now - latest_candle_close`
- `expected_interval = 60s`
- `delay_ratio = candle_age_seconds / 60`

2. Built distribution metrics:
- p50, p90, p99, max
- `% symbols > 2x expected`
- `% symbols > 5x expected`

3. Compared snapshot age vs candle age per symbol:
- snapshot source: `.runtime/state/revolut_universe_price_history.json`
- `snapshot_age_seconds = now - latest_snapshot_ts`
- checked divergence between snapshot and candle ages to detect caching/reuse drift

4. Cross-checked with runtime SLO context:
- source: `.runtime/state/market_sync_health.json`

## Results

## 1) Per-symbol decision-timeframe freshness (1m)

Universe size: **77 symbols**

### Candle age distribution
- p50: **198.7s**
- p90: **258.7s**
- p99: **318.7s**
- max: **318.7s**

### Delay ratio distribution (`age / 60s`)
- p50: **3.31x**
- p90: **4.31x**
- p99: **5.31x**
- max: **5.31x**

### Breach percentages
- `% symbols > 2x` (older than 120s): **74.0%**
- `% symbols > 5x` (older than 300s): **9.1%**
- `% symbols > 7x`: **0%**

Interpretation: data is present and advancing, but most 1m candles are materially older than the ideal decision freshness target.

## 2) Snapshot age vs candle age (caching/reuse consistency)

Symbols compared: **77/77** (no missing snapshot age)

### Divergence stats (`snapshot_age - candle_age`)
- p50: **-129.1s**
- p90: **-9.1s**
- mean: **-104.9s**
- max absolute divergence: **249.1s**
- symbols with `|diff| > 120s`: **42**
- symbols with ratio divergence (`snapshot/candle >2` or `<0.5`): **47**

### What this means
- For many symbols, snapshot age is much fresher than candle age.
- This is consistent with current architecture where snapshot/quote stream updates more frequently than 1m candle ingestion.
- Not direct evidence of DB corruption; it is evidence of **freshness-domain mismatch** (fresh quote snapshots + older candle-derived features).

## 3) Top stale symbols at capture time (examples)

Oldest observed (~318.7s):
- `ADA-USD`, `APT-USD`, `GTC-USD`, `KAITO-USD`, `SOL-USD`, `UNI-USD`, `XTZ-USD`

Next bucket (~258.7s):
- `AAVE-USD`, `API3-USD`, `ARPA-USD`, `BONK-USD`, `BTC-USD`, `FLOKI-USD`, `KAVA-USD`, `LTC-USD`

## 4) Runtime SLO cross-check

From latest health snapshot:
- `decision_due_jobs`: 72
- `decision_selected_jobs`: 5
- `decision_oldest_due_age_seconds`: ~288.8s
- `fresh_decision`: 70 (point-in-time)
- `decision_timeframe_max_oldest_due_seconds` threshold: 420.0s

Interpretation:
- System remains under configured SLO threshold, but still runs with high practical decision-candle lag for many symbols.
- This confirms throughput/capacity pressure rather than endpoint/storage failure.

## Phase 2 Conclusion

Freshness is **not broken by missing data**, but it is **degraded by ingestion service rate vs due-workload**:
- Most symbols are 2x-5x older than ideal 1m freshness.
- Snapshot layers can appear fresh while candle-based features are older.

This supports the Phase 1 diagnosis:
- primary issue is ingestion servicing pressure/starvation pattern,
- not API outage and not SQLite integrity failure.
