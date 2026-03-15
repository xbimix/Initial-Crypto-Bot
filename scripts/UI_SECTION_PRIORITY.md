# UI Section Priority Hierarchy (Pre-Redesign)

Last updated: 2026-03-15
Purpose: preserve operational value while redesigning presentation.

## Main Dashboard Priority

Priority 1 (must be visible first):
1. Runtime status and control state
2. Risk guard state (daily loss pause, trade window, exposure/cooldown)
3. Open positions health (unrealized PnL, stale review, max drawdown indicators)

Priority 2 (operator decision support):
1. Token controls and execution diagnostics
2. Volatility Opportunity Radar ranking
3. Rolling Symbol Rotation Monitor
4. Best-buy advisory + top risk/capital drag indicators

Priority 3 (context and trend):
1. Equity curve and cash/exposure summary
2. Recent trade activity metadata
3. Secondary diagnostics/details

## Token Page Priority

Priority 1 (position truth):
1. Current price, position size, market value
2. Unrealized PnL USD/% and position age
3. Max drawdown since entry
4. Stale losing review status

Priority 2 (near-term advisory intelligence):
1. Volatility Opportunity card (score/label/reason/subscores/confidence/insufficiency)
2. Wave Zone Analyzer summary (weighted low/high revisit + dominant bias)
3. Wave timeframe breakdown with insufficiency reasons

Priority 3 (historical and operational context):
1. Rotation monitor metrics for the symbol
2. Price snapshot trail chart
3. Recent token trade history and reasons

## Design Constraint Notes

1. Advisory sections remain explicitly non-execution.
2. Strategy/execution controls should remain distinguishable from analytics.
3. Any section reorder in redesign should preserve this semantic priority unless explicitly changed.
