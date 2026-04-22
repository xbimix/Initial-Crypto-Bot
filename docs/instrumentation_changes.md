# Instrumentation Changes

## Scope

This pass adds observability fields only for BUY-path diagnostics in decision audit rows.
No strategy, routing, threshold, or execution logic was changed.

## Code Changes

- Added `main._resolve_buy_path_observability(...)` in [main.py](D:\Python-Codes\RevBot\crypto_bot\main.py)
  - Derives BUY diagnostics from existing `decision`, `market`, and `cfg` context.
  - Read-only computation; no branching/decision mutation.

- Extended `_append_decision_audit(...)` payload in [main.py](D:\Python-Codes\RevBot\crypto_bot\main.py) with:
  - `buy_score_actual`
  - `buy_score_threshold`
  - `buy_zscore_actual`
  - `buy_zscore_threshold`
  - `buy_stretch_actual`
  - `buy_stretch_threshold`
  - `buy_price_position_in_range`
  - `buy_zone_low`
  - `buy_zone_high`
  - `buy_route_name`

## Backward Compatibility

- Existing fields remain unchanged.
- Existing schema markers (`schema_name`, `schema_version`) unchanged.
- New fields are additive and nullable when unavailable.
- Existing audit consumers remain compatible.

## Tests Added

In [test_main_runtime.py](D:\Python-Codes\RevBot\crypto_bot\tests\test_main_runtime.py):

- `test_append_decision_audit_emits_buy_observability_for_blocked_buy_path`
  - Verifies all 10 fields on a blocked BUY evaluation (`score_below_threshold`).

- `test_append_decision_audit_emits_buy_observability_for_passed_buy_path`
  - Verifies all 10 fields on a passed BUY evaluation (`action=BUY`, executed).

## Validation Run

Executed:

```bash
python -m pytest -q D:\Python-Codes\RevBot\crypto_bot\tests\test_main_runtime.py -k "append_decision_audit or resolve_decision_gate_diagnostics"
```

Result: `7 passed`.

## Latest Runtime Verification (Last 12h)

- Total rows analysed: `11955`
- `score_below_threshold` rows analysed: `2677`
- `buy_score_actual` coverage (all rows): `359/11955`
- `buy_score_threshold` coverage (all rows): `468/11955`
- `buy_route_name` coverage (all rows): `427/11955`

## Runtime Recheck (Updated)

- Last-12h rows: `11979`; post-population rows: `492`
- First populated row timestamp: `2026-04-12 18:40:59 UTC`
- Post-population `buy_score_threshold` coverage: `492/492`
- Post-population `buy_zscore_actual` coverage: `492/492`
- Post-population `buy_price_position_in_range` coverage: `0/492`
