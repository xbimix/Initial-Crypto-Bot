# Strategy Input Failure Report (Phase 4)

Date: 2026-04-09  
Window: 2026-04-08T07:30:36Z -> 2026-04-09T07:30:36Z (last 24h)  
Source: `.runtime/state/decision_audit.jsonl`  
Scope: validation only (no strategy/routing/threshold changes)

## Decision Trace Summary

- Total cycles: **16,342**
- Trades executed: **0**
- Blocked cycles: **16,342**

## Top 5 Block Reasons (with %)

1. `price_above_buy_zone` -> **4,277 (26.17%)**
2. `price_below_buy_zone` -> **2,734 (16.73%)**
3. `core_not_ready:1h:stale` -> **2,654 (16.24%)**
4. `score_below_threshold` -> **1,721 (10.53%)**
5. `waiting_for_first_lock` -> **1,179 (7.21%)**

## Classification Buckets

- `other` (strategy/rule-level holds): **9,837 (60.19%)**
- `stale_data`: **2,654 (16.24%)**
- `insufficient_data`: **2,573 (15.74%)**
- `low_volatility`: **1,278 (7.82%)**
- `missing_inputs`: **0 (0.00%)**

## Top Reason Deep Dive

Top reason: `price_above_buy_zone`

- Exact condition triggered:
  - `gate_trigger_condition = "range_position <= buy_zone_high"`
- Threshold used:
  - Not persisted in this row (`gate_trigger_threshold = null`)
- Actual observed value:
  - Not persisted in this row (`gate_trigger_actual = null`)
- Was decision correct:
  - **Likely yes**, based on reason semantics (`price_above_buy_zone` implies condition failed).
  - Observability gap remains: threshold/actual are not consistently materialized for this gate.

Representative row for this reason:
- `symbol=ZRX-USD`
- `decision_reason=price_above_buy_zone`
- `data_quality_status=GOOD`
- `candle_age_seconds=261.929`
- `atr_raw=0.0007968127490039516`

## Requested Field Validation (blocked attempts)

All blocked rows contain the requested strategy-input fields with high consistency:
- `symbol`
- `atr_raw`
- `data_quality_status`
- `candle_age_seconds`
- `decision_reason` / `strategy_eval_gate_blocked_reason`

Examples by class:

- `stale_data`:
  - `XRP-USD`, reason `core_not_ready:1h:stale`, `dq=GOOD`, `age=64.121`, `atr=0.0004369674`
- `insufficient_data`:
  - `ZK-USD`, reason `core_not_ready:1h:stale,4h:insufficient_depth,1d:insufficient_depth`, `dq=GOOD`, `age=125.028`, `atr=0.0004932858`
- `low_volatility`:
  - `TRX-USD`, reason `atr_too_low`, `dq=GOOD`, `age=262.280`, `atr=0.0002197526`
- `other`:
  - `XYO-USD`, reason `price_below_buy_zone`, `dq=GOOD`, `age=304.691`, `atr=0.0008270857`

## Input/Freshness Shape in Blocked Set

- `candle_age_seconds` distribution in blocked set:
  - p50: **154.608s**
  - p90: **258.091s**
  - max: **321.507s**

Interpretation:
- The blocked population is mixed:
  - a large share are pure strategy-rule holds (`buy_zone`, `score`, lock sequencing),
  - but stale/insufficient readiness is still a material blocker.

## Phase 4 Conclusion

The strategy input boundary is populated and auditable; current non-execution is not due to missing payload fields.  
Main blockers in this 24h window are:
1. rule-level hold logic (`buy_zone` and score filters), and
2. core-timeframe readiness degradation (`1h` stale / insufficient depth combinations).

