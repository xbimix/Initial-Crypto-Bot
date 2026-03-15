# UI Vocabulary Map (Backend -> Human)

Last updated: 2026-03-15
Purpose: keep naming consistent during redesign without changing backend behavior.

## Core Trading/State Terms

- `buyOpportunityPct` -> `Buy Opportunity`
- `buyExecutable` -> `Buy Executable`
- `buyExecutableReason` -> `Buy Block/Ready Reason`
- `capitalEfficiencyScore` -> `Capital Efficiency Score`
- `capitalWasteRank` -> `Capital Waste Rank`
- `advisoryStaleLosingReview` -> `Stale Losing Review Flag`
- `advisoryMaxDrawdownPctDuringTrade` -> `Max Drawdown During Trade (%)`

## Rotation Monitor

- `rotationShortTermScore` -> `Rotation Short-Term Score`
- `rotationMediumTermScore` -> `Rotation Medium-Term Score`
- `rotationDelta` -> `Rotation Delta (Short - Medium)`
- `rotationStatus` values:
  - `Rising` -> `Rising`
  - `Strong` -> `Strong`
  - `Neutral` -> `Neutral`
  - `Weakening` -> `Weakening`
  - `Cold` -> `Cold`
  - `Capital Trap Risk` -> `Capital Trap Risk`

## Volatility Opportunity Radar

- `volatilityOpportunityScore` -> `Volatility Opportunity Score`
- `volatilityOpportunityLabel` values:
  - `HIGH` -> `High Opportunity`
  - `MEDIUM` -> `Moderate Opportunity`
  - `LOW` -> `Low Opportunity`
- `volatilityOpportunityReason` -> `Opportunity Reason`
- `volatilityOpportunityConfidenceLabel` values:
  - `HIGH` -> `High Confidence`
  - `MEDIUM` -> `Medium Confidence`
  - `LOW` -> `Low Confidence`
- `volatilityOpportunityStretchScore` -> `Stretch`
- `volatilityOpportunityVolatilitySpikeScore` -> `Volatility Spike`
- `volatilityOpportunityBounceContextScore` -> `Bounce Context`
- `volatilityOpportunityLiquidityQualityScore` -> `Liquidity Quality`
- `volatilityOpportunityInsufficientData` -> `Insufficient Data`
- `volatilityOpportunityInsufficientReasonCode` mapping:
  - `insufficient_point_count` -> `Not Enough Data Points`
  - `insufficient_history_span` -> `History Window Too Short`
  - `stale_snapshot_history` -> `Snapshot History Is Stale`
  - `insufficient_window_coverage` -> `Window Coverage Too Thin`
  - `invalid_price_window` -> `Invalid Price Window`

## Wave Zone Analyzer

- `dominant_bias` values:
  - `LOW_REVISIT_MORE_LIKELY` -> `Low Zone Magnet`
  - `HIGH_REVISIT_MORE_LIKELY` -> `High Zone Magnet`
  - `BALANCED` -> `Balanced Bias`
- `weighted_low_revisit_likelihood_pct` -> `Weighted Low Revisit Likelihood`
- `weighted_high_revisit_likelihood_pct` -> `Weighted High Revisit Likelihood`
- `strongest_overall_low_zone` -> `Strongest Overall Support Zone`
- `strongest_overall_high_zone` -> `Strongest Overall Resistance Zone`

Per-timeframe insufficiency codes:
- `insufficient_history_span` -> `Insufficient History Span`
- `insufficient_candle_count` -> `Insufficient Candle Count`
- `no_valid_pivots` -> `No Valid Pivots`
- `stale_snapshot_history` -> `Stale Snapshot History`

## Report Freshness Terms

- `generated_at` / `generated_at_utc` -> `Report Generated At`
- `coverage` -> `Coverage Window`
- `freshness.indicator`:
  - `fresh` -> `Fresh`
  - `stale` -> `Stale`
