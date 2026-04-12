# Root Cause Analysis (Phase 5)

Date: 2026-04-09  
Inputs:
- `docs/data_pipeline_audit.md`
- `docs/data_freshness_report.md`
- `docs/feature_integrity_report.md`
- `docs/strategy_input_failure_report.md`
- `.runtime/state/market_sync_health.json` (latest snapshot)

## Classification (A/B/C/D/E)

Primary cause: **A/B combined (ingestion starvation + scheduler bottleneck)**  
Confidence: **High**

Secondary causes:
- **D. API-usage pressure envelope mismatch** (Medium): REST pull + broad symbol/timeframe workload.
- **E. Indicator miscalculation** (Low): not supported by measured ATR/feature integrity.
- **C. Data overwrite/corruption** (Low): SQLite integrity checks are clean.

Operational note:
- In the latest 24h window, non-execution is additionally dominated by **strategy-rule holds** (`price_above_buy_zone`, `price_below_buy_zone`, `score_below_threshold`), which are outside A-E data-break categories.

## Evidence Chain

1. **Freshness lag is persistent**
- 1m candle age (Phase 2): p50/p90/max ~198.7s / 258.7s / 318.7s.
- ~74.0% symbols older than 120s.

2. **Service-rate mismatch is visible in live scheduler telemetry**
- Latest sync health snapshot:
  - `request_cap=6`
  - `due 1m jobs=72`
  - `selected 1m jobs=5`
  - starvation includes `1h/1d/5m/15m`
- This confirms due-work consistently exceeds per-tick service budget.

3. **Storage is healthy**
- DB checks show:
  - no duplicate candle keys
  - no major OHLC integrity violations
  - contiguous 1m steps in sampled continuity checks

4. **Indicators are populated**
- Phase 3 showed non-zero ATR proxies across sampled universe.
- No broad `atr == 0` collapse pattern in measured window.

5. **Decision failures split**
- 24h blocked cycles: 16,342; executed: 0.
- Data-related classes:
  - stale_data: 16.24%
  - insufficient_data: 15.74%
  - low_volatility: 7.82%
- Rule-level holds (`other`): 60.19%, led by `price_above_buy_zone` and `price_below_buy_zone`.

## Determination

For the **data pipeline**, the principal failure remains **under-served ingestion workload** (A/B).  
For **zero executions in this specific 24h window**, strategy-rule holds are the largest immediate blocker, with data-readiness issues still materially contributing.

