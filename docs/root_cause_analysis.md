# Root Cause Analysis (Phase 5)

Date: 2026-04-08

## Classification

Primary cause: **B. Scheduler bottleneck / fairness pathology**  
Confidence: **High**

Secondary causes:
- **A. Ingestion starvation under workload pressure** (high)
- **D. API usage overhead from broad fallback probing** (medium)
- **E. Indicator miscalculation** (low, currently not dominant)
- **C. Data overwrite/corruption** (low, no evidence)

## Evidence chain

1. Due-vs-capacity mismatch
- Scheduler due jobs frequently ~`384-449`
- Selected jobs fixed at `6` (`max_sync_requests_per_tick=6`)
- Persistent starvation telemetry for non-decision timeframes

2. Decision path impact
- Frequent live reasons: `core_not_ready:*stale/insufficient_depth*`, `market_data_quality:stale`
- Freshness entry guard repeatedly activated

3. Integrity checks
- No duplicate candle key rows
- Stable 1m ordering in sampled rows
- ATR populated across symbols (not zero-collapse driven)

4. API contract
- Fetch shape matches `/candles/{symbol}` contract
- Main issue is not endpoint mismatch; it is operational scheduling/coverage pressure

## What this means operationally

- System quality degradation is dominated by **coverage lag across required windows** under constrained tick budget.
- Decision gating then correctly blocks entries for safety, resulting in low execution frequency.

