# Decision Gate Map (Last 12h)

Generated from `.runtime/state/decision_audit.jsonl` using `ts_epoch` in the last 12 hours.

- Total decision cycles: `14,777`
- Actions observed: `HOLD` only
- Trades executed: `0`

## Entry Gates

Entry-gate denominator: `13,554`  
Columns: `count | % of entry-gate blocks | % of all cycles`

| Reason Code | Count | % Entry | % Total |
|---|---:|---:|---:|
| `price_above_buy_zone` | 7,590 | 56.00% | 51.36% |
| `price_below_buy_zone` | 3,242 | 23.92% | 21.94% |
| `core_not_ready:1h:insufficient_depth,4h:insufficient_depth,1d:insufficient_depth` | 1,249 | 9.21% | 8.45% |
| `scalper_momentum_not_ready` | 440 | 3.25% | 2.98% |
| `atr_too_low` | 403 | 2.97% | 2.73% |
| `insufficient_volatility_stretch` | 260 | 1.92% | 1.76% |
| `score_below_threshold` | 142 | 1.05% | 0.96% |
| `core_not_ready:1h:stale` | 101 | 0.75% | 0.68% |
| `regime_unknown` | 47 | 0.35% | 0.32% |
| `core_not_ready:1h:insufficient_depth,4h:insufficient_depth` | 31 | 0.23% | 0.21% |
| `scalper_too_extended` | 30 | 0.22% | 0.20% |
| `core_not_ready:1h:stale,4h:insufficient_depth,1d:insufficient_depth` | 16 | 0.12% | 0.11% |
| `scalper_wait_for_pullback` | 2 | 0.01% | 0.01% |
| `core_not_ready:1h:stale,4h:insufficient_depth` | 1 | 0.01% | 0.01% |

## Exit Gates

Exit-gate denominator: `1,223`  
Columns: `count | % of exit holds | % of all cycles`

| Reason Code | Count | % Exit | % Total |
|---|---:|---:|---:|
| `waiting_for_first_lock` | 1,047 | 85.61% | 7.09% |
| `in_position` | 176 | 14.39% | 1.19% |

## Execution Gates

Execution-gate denominator: `0`

- `execution_status` non-empty rows: `0`
- `execution_reason` non-empty rows: `0`
- `blocked_reason` non-empty rows: `0`

No execution-layer gate/rejection reason codes were emitted in this window because no BUY/SELL attempts reached execution.

