# Feature Integrity Report (Phase 3)

Date: 2026-04-08  
Inputs:
- `.runtime/state/bot.runtime.log` latest `SNAPSHOT` lines
- `.runtime/state/market_data.db` recent 1m closes per symbol

## Checks executed

1. Indicator presence and distribution from latest snapshot payloads
2. ATR-zero / tiny-ATR incidence
3. Return-series quality over last 120 closes:
   - volatility proxy (`std(returns)`)
   - zero-return ratio
4. Cause classification for observed weak indicators

## Snapshot indicator integrity

- Symbols with snapshot metrics: `77`
- ATR values present: `77/77`
- ATR distribution:
  - `min`: `0.00021975`
  - `p50`: `0.00069735`
  - `p90`: `0.00181159`
  - `max`: `0.01142857`
- `ATR == 0`: `0`
- `ATR < 1e-6`: `0`

Quality status in latest snapshots:
- `ok`: `57`
- `candle_history_stale`: `17`
- `spread_too_wide,candle_history_stale`: `2`
- `spread_too_wide`: `1`

## Return-series integrity (last 120 closes)

No broad missing-history issue:
- computed symbols: `77`
- all sampled symbols had sufficient close history for return calculation

Observed microstructure artifact (important):
- Some symbols show very high zero-return ratios on 1m (`0.80-0.94`), which depresses realized short-horizon variation.
- This is a market/data granularity characteristic for low-turnover pairs, not a parser corruption signal.

Examples (highest zero-return ratios):
- `SPELL-USD` `0.941`
- `POLS-USD` `0.933`
- `HFT-USD` `0.933`
- `FLOKI-USD` `0.933`
- `ASM-USD` `0.916`
- `MLN-USD` `0.916`

## Conclusion

1. Indicators are populated; ATR collapse-to-zero is **not** currently the dominant failure mode.
2. Main integrity risk is freshness/coverage quality (`core_not_ready`, `stale`), not missing ATR computation.
3. For thin symbols, high zero-return ratios can make volatility features less expressive; this is a data-quality/market-activity issue rather than calculation breakage.

