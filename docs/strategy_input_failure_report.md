# Strategy Input Failure Report (Phase 4)

Date: 2026-04-08  
Goal: classify blocked decision inputs without changing strategy logic.

## Data sources

- `.runtime/state/decision_audit.jsonl` (last 24h summary)
- `.runtime/state/bot.runtime.log` (recent runtime decision + snapshot context)

## Decision outcomes (last 24h)

- Total decisions: `17650`
- Executed BUY: `70`
- Blocked/non-BUY: `17580`

Top block reasons (24h):
- `price_above_buy_zone`: `4737`
- `price_below_buy_zone`: `4509`
- `score_below_threshold`: `2638`
- `insufficient_volatility_stretch`: `1646`
- `waiting_for_first_lock`: `1390`
- `regime_unknown`: `1069`
- `scalper_momentum_not_ready`: `462`
- `core_not_ready:1h:insufficient_depth,4h:insufficient_depth,1d:insufficient_depth`: `358`
- `market_data_quality:stale`: `210`
- `atr_too_low`: `194`

## Runtime-window classification (recent live stream)

From recent `bot.runtime.log` decision rows with directly adjacent snapshot context:
- analyzed rows: `325`
- stale/core-data-gated: `325` (`100%`)

Dominant reasons in this window:
- `core_not_ready:1h:insufficient_depth,4h:insufficient_depth,1d:insufficient_depth`
- `core_not_ready:4h:stale`
- `core_not_ready:1h:stale,4h:stale`
- `market_data_quality:stale`

## Required fields requested by audit

Requested per blocked decision:
- `symbol`
- `ATR`
- `data_quality_status`
- `candle_age`
- `block_reason`

Current state:
- `symbol` and `block_reason` are consistently available.
- `ATR` and `quality` are available from runtime snapshot stream.
- exact per-decision `candle_age_seconds` is not consistently persisted in `decision_audit.jsonl` rows.

Gap:
- Decision audit schema should include explicit candle-age-at-decision for full forensic traceability.

## Conclusion

1. Current low execution frequency is primarily due to gate conditions, with a significant live contribution from stale/core readiness conditions.
2. Observability is improved but still missing exact per-decision candle-age persistence in audit rows.

