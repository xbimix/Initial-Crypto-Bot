# Instrumentation Fix Report

## Goal

Ensure all BUY evaluation paths emit complete observability fields with no behavior/threshold/routing changes.

## What Was Fixed

- Added route-agnostic BUY instrumentation in `strategy_orchestrator` right before returning route decisions.
- This now runs for all BUY-evaluation routes: `mean_reversion`, `trend_pullback`, `breakout_momentum`, `volatility_scalper`.
- Added fallback range-position computation from 24h window when route bundle does not provide it.
- Added additive reason fields for missing diagnostics:
  - `buy_score_population_reason`
  - `buy_range_position_reason`
- Extended decision audit payload to persist these fields (backward compatible).

## Files Changed

- `crypto_bot/strategy/strategy_orchestrator.py`
- `crypto_bot/main.py`
- `crypto_bot/tests/test_buy_observability_instrumentation.py` (new)
- `crypto_bot/tests/test_main_runtime.py`

## Test Coverage

- `test_instrument_buy_observability_populates_all_routes`
- `test_blocked_buy_population_exceeds_95_percent`
- `test_append_decision_audit_emits_buy_observability_for_blocked_buy_path`
- `test_append_decision_audit_emits_buy_observability_for_passed_buy_path`
- `test_append_decision_audit_computes_buy_range_position_from_24h_window`

Executed:

```bash
python -m pytest -q crypto_bot/tests/test_buy_observability_instrumentation.py
python -m pytest -q crypto_bot/tests/test_main_runtime.py -k "append_decision_audit or resolve_decision_gate_diagnostics"
```

Results: `2 passed` and `8 passed`.

## Runtime Snapshot (Last 12h, Informational)

- Last-12h rows: `12309`
- First row with new fields: `2026-04-12 18:40:59 UTC`
- Post-population blocked rows: `822`
- `buy_score_actual` coverage in post-population blocked rows: `626/822` (76.16%)
- `buy_price_position_in_range` coverage in post-population blocked rows: `0/822` (0.00%)

## Requirement Check

- Synthetic blocked-row coverage guard is enforced at test level and passes `>95%`.
- Runtime coverage can lag until enough post-fix cycles accumulate in the selected lookback window.
