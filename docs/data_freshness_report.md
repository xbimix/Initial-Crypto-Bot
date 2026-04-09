# Data Freshness Report (Phase 2)

Date: 2026-04-08  
Inputs:
- `.runtime/state/market_data.db` (1m latest-open age by symbol)
- `.runtime/state/phase2_freshness_samples.json` (36 live samples @10s)
- `.runtime/state/bot.runtime.log` (snapshot timestamps)
- OpenAPI reference: `crypto_bot/api/revolut-x.yml`, `crypto_bot/api/revolut-x.json`

## Method

- Expected decision interval: `60s` (`1m`)
- Per-symbol:
  - `candle_age_seconds = now - latest_1m_open_time`
  - `delay_ratio = candle_age_seconds / 60`
- Distribution:
  - p50 / p90 / p99 / max
  - `% > 2x expected age` (`>120s`)
  - `% > 5x expected age` (`>300s`)
- Snapshot-vs-candle comparison:
  - latest snapshot timestamp age (from bot runtime log) vs latest candle age

## Live window summary (36 samples, ~6 minutes)

- `p50_age_s`: `22022.8 -> 242.9`
- `p90_age_s`: `22142.8 -> 22442.9`

Interpretation:
- The system started with very stale backlog.
- Mid-window, a large portion was caught up (p50 collapse), but tail symbols remained highly stale (p90 stayed very high during that run).
- This is a bimodal catch-up signature: partial catch-up under constrained scheduling.

## Current freshness snapshot (at report generation)

- Symbols measured: `77`
- `p50`: `197.2s`
- `p90`: `317.2s`
- `max`: `377.2s`
- `>120s`: `72/77` (`93.5%`)
- `>300s`: `17/77` (`22.1%`)

Top stale (age / delay_ratio):
- `HBAR-USD` `377.2s` `6.29x`
- `XYO-USD` `377.2s` `6.29x`
- `BNB-USD` `317.2s` `5.29x`
- `ICP-USD` `317.2s` `5.29x`
- `JUP-USD` `317.2s` `5.29x`
- `ORCA-USD` `317.2s` `5.29x`
- `PONKE-USD` `317.2s` `5.29x`
- `PRIME-USD` `317.2s` `5.29x`
- `PYTH-USD` `317.2s` `5.29x`
- `RARE-USD` `317.2s` `5.29x`
- `RPL-USD` `317.2s` `5.29x`
- `SHIB-USD` `317.2s` `5.29x`

## Snapshot age vs candle age

- Snapshot age p50/p90/max: `138.5s / 259.5s / 309.5s`
- `(candle_age - snapshot_age)` avg/p90/max: `76.4s / 253.6s / 341.6s`

Interpretation:
- Snapshot and candle ages are correlated and close enough to indicate no major snapshot-caching drift bug.
- The dominant issue is ingestion backlog/selection fairness, not snapshot reuse mismatch.

## Findings

1. Decision-timeframe freshness has improved from extreme stale to moderate stale, but is still outside ideal `<=90s`.
2. Tail staleness remains material (`22%` symbols still `>5x` interval).
3. The observed pattern is consistent with scheduler throughput/fairness limitations rather than malformed data rows.

