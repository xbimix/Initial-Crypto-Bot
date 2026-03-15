# UI Payload Contracts (Pre-Redesign Freeze)

Last updated: 2026-03-15
Status: frozen for UI redesign compatibility

## Scope

This document freezes the payload contracts consumed by the current dashboard and token pages.

Sources:
- `web-ui/src/app/api/dashboard/route.ts`
- `web-ui/src/app/api/token/[symbol]/route.ts`

Rules:
1. Keep existing keys backward-compatible during redesign.
2. Additive fields are allowed.
3. Renames/removals require a compatibility wrapper and migration note.

## `/api/dashboard` (GET)

Top-level keys:
- `generatedAt: string`
- `summary: object`
- `symbolControls: object[]`
- `chart: { points: number[]; min: number; max: number }`
- `positions: object[]`

### `summary` contract

Core runtime/account:
- `enabled`, `executionMode`, `trackedSymbols`, `activeSymbols`, `disabledSymbols`
- `sellEnabledSymbols`, `sellDisabledSymbols`
- `startingBalance`, `cashBalance`, `investedCapital`, `openValue`, `totalEquity`
- `realizedPnl`, `unrealizedPnl`, `netPnl`, `netReturnPct`
- `openPositions`, `openExposurePct`
- `lastTradeAt`, `lastTradeReason`, `lastSnapshotAt`
- `buyCount`, `sellCount`

Risk/control:
- `cooldownSeconds`, `maxConcurrentTrades`, `maxConcurrentTradesPerToken`
- `maxTradeAmountUsd`, `tradeAmountUsd`, `riskPercent`
- `maxPortfolioExposurePct`, `maxExposurePerTokenPct`
- `signalConfirmationCycles`
- `tradeWindowEnabled`, `tradeWindowStartHourUtc`, `tradeWindowEndHourUtc`, `insideTradeWindowUtc`
- `dailyLossLimitUsd`, `dailyLossAutoPause`, `dailyLossCloseAll`, `dailyRealizedPnlUsd`, `dailyBuyPaused`
- `symbolCooldownOverrides`

Advisory summary:
- `staleLosingReviewCount`, `staleLosingReviewSymbols`
- `staleLosingReviewThresholdAgeHours`, `staleLosingReviewThresholdUnrealizedPnlPct`
- `maxDrawdownDuringTradePct`, `maxDrawdownDuringTradeSymbol`
- `bestBuySymbol`, `bestBuyOpportunityPct`
- Rotation: `rotationRisingCount`, `rotationStrongCount`, `rotationNeutralCount`, `rotationWeakeningCount`, `rotationColdCount`, `rotationCapitalTrapRiskCount`, `rotationTopRisingSymbols`, `rotationTopColdSymbols`
- Volatility radar: `topVolatilityOpportunitySymbols`, `highestVolatilityOpportunityScore`, `highOpportunitySymbolCount`

### `symbolControls[]` contract

Identity/toggles:
- `symbol`, `buyEnabled`, `sellEnabled`, `hasOpenPosition`, `scalperEnabled`
- `cooldownOverrideSeconds`

Execution diagnostics:
- `buyExecutable`, `buyExecutableReason`
- `regime`, `volatilityPct`, `strategyScorePct`, `buyOpportunityPct`

Advisory metrics:
- Capital efficiency: `capitalEfficiencyScore`, `capitalWasteRank`, `capitalWasteAllocationPct`, `capitalWasteUnrealizedPct`, `capitalWasteAgeHours`
- Rotation monitor:
  `rotationShortTermScore`, `rotationMediumTermScore`, `rotationDelta`, `rotationStatus`,
  `rotationShortTermWinRatePct`, `rotationShortTermAvgRealizedPnlUsd`, `rotationShortTermAvgHoldHours`,
  `rotationShortTermAvgRecoveryHours`, `rotationShortTermStaleReviewFrequencyPct`, `rotationShortTermAvgMaxDrawdownPct`,
  `rotationMediumTermWinRatePct`, `rotationMediumTermAvgRealizedPnlUsd`, `rotationMediumTermAvgHoldHours`,
  `rotationMediumTermAvgRecoveryHours`, `rotationMediumTermStaleReviewFrequencyPct`, `rotationMediumTermAvgMaxDrawdownPct`
- Volatility opportunity radar:
  `volatilityOpportunityScore`, `volatilityOpportunityLabel`, `volatilityOpportunityReason`,
  `volatilityOpportunityConfidenceLabel`, `volatilityOpportunityStretchScore`,
  `volatilityOpportunityVolatilitySpikeScore`, `volatilityOpportunityBounceContextScore`,
  `volatilityOpportunityLiquidityQualityScore`, `volatilityOpportunityObservedHistorySpanMinutes`,
  `volatilityOpportunityObservedPointCount`, `volatilityOpportunityInsufficientData`,
  `volatilityOpportunityInsufficientReasonCode`, `volatilityOpportunityInsufficientReasonMessage`

### `positions[]` contract

- `symbol`, `units`, `entryPrice`, `currentPrice`, `lockPrice`
- `costBasis`, `marketValue`, `allocationPct`
- `unrealizedValue`, `unrealizedPct`, `peakPnlPct`, `profitLockPct`, `status`
- `entryTime`, `thesis`
- Advisory:
  `advisoryStaleLosingReview`, `advisoryReviewAgeHours`,
  `advisoryThresholdAgeHours`, `advisoryThresholdUnrealizedPnlPct`,
  `advisoryMaxDrawdownPctDuringTrade`, `advisoryMaxDrawdownPriceDuringTrade`, `advisoryMaxDrawdownAt`

## `/api/token/[symbol]` (GET)

Top-level keys:
- `generatedAt`, `symbol`
- `summary`
- `advisory`
- `history`
- `chart`
- `waveZoneAnalyzer`

### `summary` contract

- `symbol`, `currentPrice`, `currentPriceAt`
- `hasOpenPosition`, `openUnits`, `entryPrice`
- `marketValue`, `unrealizedPnlUsd`, `unrealizedPnlPct`
- `positionAgeHours`
- `maxDrawdownSinceEntryPct`, `maxDrawdownSinceEntryPrice`, `maxDrawdownSinceEntryAt`

### `advisory` contract

- Stale review:
  `staleLosingReview`, `staleReviewAgeHours`, `staleReviewThresholdAgeHours`, `staleReviewThresholdUnrealizedPnlPct`
- Opportunity:
  `volatilityOpportunityScorePct`, `volatilityOpportunityLabel`
- Detailed volatility radar (`volatilityOpportunity`):
  `score`, `label`, `reason`, `confidenceLabel`,
  `stretchScore`, `volatilitySpikeScore`, `bounceContextScore`, `liquidityQualityScore`,
  `observedHistorySpanMinutes`, `observedPointCount`,
  `insufficientData`, `insufficientReasonCode`, `insufficientReasonMessage`
- Existing diagnostics:
  `regime`, `strategyScorePct`, `volatilityPct`, `buyExecutable`, `buyExecutableReason`,
  `capitalEfficiencyScore`, `capitalWasteRank`
- Rotation monitor: `rotationMonitor` object with `shortTerm`, `mediumTerm`, `status`, `rotationDelta`

### `history` contract

- `buyCount`, `sellCount`, `realizedPnlUsd`
- `recentTrades[]` with `time`, `side`, `price`, `size`, `reason`, `pnl`, `balance`

### `chart` contract

- `pricePoints[]`, `pricePointCount`, `historySource`
- `tradeMarkers[]`

### `waveZoneAnalyzer` contract

Frozen as provided by `waveZoneAnalyzer.mjs`:
- `summary` (weighted revisit likelihoods, dominant bias, strongest zones, quality notes)
- `timeframes` keyed by `1h`, `4h`, `8h`, `16h`, `24h`, `3d`, `7d`
- Per-timeframe insufficiency metadata preserved:
  `insufficient_data`, `insufficient_reason_code`, `insufficient_reason_message`, `observed_history_span_minutes`, `observed_candle_count`

## Compatibility Notes

1. UI redesign must preserve all above fields or provide a translation layer.
2. Advisory fields must remain read-time and non-execution.
3. Strategy/execution behavior remains outside UI contracts.
