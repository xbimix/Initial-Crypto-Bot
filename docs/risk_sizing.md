# Risk Sizing

## Contract
`RiskManager` now exposes a typed sizing contract:
- `position_sizing(...) -> PositionSizingResult`
- Backward-compatible scalar API remains:
  - `position_size(...) -> float` (returns `PositionSizingResult.capped_size`)

`PositionSizingResult` includes:
- `raw_size`, `capped_size`
- `risk_budget_used_usd`
- `stop_distance`, `per_unit_risk_usd`
- expected fee/slippage assumptions
- raw/capped notional
- `rejected_reason` when size resolves to zero

## Primary sizing logic
Primary mode is stop-distance risk sizing (configurable):
- `size_by_stop = risk_budget_usd / per_unit_risk_usd`
- `per_unit_risk_usd = stop_distance + entry_price * expected_cost_pct`

The final size is constrained by:
- capital budget mode (`auto`, `stop_distance`, `fixed_usd`, `risk_percent`)
- volatility scaling
- spread/liquidity gates
- max notional caps
- portfolio/symbol exposure caps
- minimum trade notional
- optional liquidity notional cap

## Compatibility
- Existing `risk_percent` and `trade_amount_usd` configs remain supported.
- `sizing_mode=auto` preserves legacy-friendly behavior while enabling stop-distance-aware sizing when a valid stop is present.

## New risk config knobs
- `risk.sizing_mode`
- `risk.min_trade_notional_usd`
- `risk.max_notional_usd`
- `risk.liquidity_cap_notional_usd`
- `risk.block_bad_market_quality`
- `risk.max_consecutive_execution_failures`
- `risk.execution_failure_pause_seconds`
