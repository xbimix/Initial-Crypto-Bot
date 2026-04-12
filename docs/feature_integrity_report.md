# Feature Integrity Report (Phase 3)

Date: 2026-04-09 (UTC)
Scope: Indicator integrity check only (no strategy/routing/threshold changes)
Runtime sources:
- `.runtime/state/market_data.db`
- `.runtime/state/config.json`

## Method

For each symbol (`timeframe=1m`), using latest 600 candles:

1. Extracted closes/highs/lows.
2. Computed close-return ATR proxy (same intent as runtime feature path):
   - `d_i = abs(close_i - close_{i-1}) / close_{i-1}`
   - `atr_close = median(non_zero(d_i))`
3. Computed range ATR proxy:
   - `r_i = (high_i - low_i) / close_i`
   - `atr_hl = median(non_zero(r_i))`
4. Effective volatility proxy:
   - `effective_atr = max(atr_close, atr_hl)`
5. Classified failure causes:
   - `stale_data` if candle age > stale threshold
   - `insufficient_candles` if rows < `min_history_points`
   - `close_quantization_or_flat_closes` if `atr_close == 0 && atr_hl > 0`
   - `zero_volatility_inputs` if both are zero

Config inputs read:
- `market_data.min_history_points = 8`
- stale threshold inferred from config = `max(decision_candle_min_stale_seconds, decision_candle_stale_intervals*60)`
  - current = `max(300, 3*60) = 420s`

## Results

## 1) ATR distribution and zero-rate

Symbols analyzed: **77**

Effective ATR proxy distribution:
- p50: **0.00539**
- p90: **0.01105**
- p99: **0.03468**
- max: **0.03468**

Zero-rate:
- `% effective_atr == 0`: **0.0%** (0/77)
- `% atr_close == 0`: **0.0%** (0/77)

Interpretation: ATR collapse-to-zero is not present in the current runtime window.

## 2) Cause classification summary

Counts:
- `stale_data`: **0**
- `insufficient_candles`: **0**
- `close_quantization_or_flat_closes`: **0**
- `zero_volatility_inputs`: **0**

Interpretation: With current DB state, feature inputs are sufficient and non-zero for all symbols at audit time.

## 3) Sample symbols with raw inputs (last 10 closes/returns)

Representative symbols checked (includes low-vol majors):
- `BTC-USD`
  - rows: 600
  - age: 37.2s
  - `atr_close=0.0003087`, `atr_hl=0.0002351`
  - non-zero returns: 397/599
  - flat close ratio: 0.337
- `ETH-USD`
  - rows: 600
  - age: 97.2s
  - `atr_close=0.0004214`, `atr_hl=0.0003052`
  - non-zero returns: 347/599
  - flat close ratio: 0.421
- `SOL-USD`
  - rows: 600
  - age: 97.2s
  - `atr_close=0.0004193`, `atr_hl=0.0007249`
  - non-zero returns: 311/599
  - flat close ratio: 0.481
- `XRP-USD`
  - rows: 600
  - age: 97.2s
  - `atr_close=0.0004097`, `atr_hl=0.0009698`
  - non-zero returns: 298/599
  - flat close ratio: 0.503

Important observation:
- Several symbols have high flat-close ratios, but ATR remains non-zero because non-zero returns still occur and/or high-low ranges carry volatility signal.

## 4) Minimum-data and insufficient-data trigger verification

Current strategy-side insufficient checks (entry paths) include:
- `trades < min_trades`
- invalid 24h range (`high_24h <= low_24h`)
- missing/invalid `vwap`
- missing/invalid `atr` or `atr <= 0`

Given current feature audit:
- `atr <= 0` is **not** the current blocking driver.
- feature integrity appears healthy; data freshness pressure (Phase 2) is the dominant concern.

## Phase 3 Conclusion

At audit time, indicators are not failing from zeroed ATR inputs.

Current bottleneck is not “indicator math broken,” but “decision-timeframe freshness lag under ingestion capacity pressure.”

Feature layer is producing valid volatility proxies; freshness/scheduling remains the primary issue to address in subsequent phases.
