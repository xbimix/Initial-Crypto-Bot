# Revolut X Data Quality Upgrade Plan

## Source Alignment
- Primary reference: `https://developer.revolut.com/docs/x-api/revolut-x-crypto-exchange-rest-api`.
- Local OpenAPI reference snapshots:
  - `crypto_bot/api/revolut-x.yml`
  - `crypto_bot/api/revolut-x.json`
- Canonical market-data endpoints validated from OpenAPI:
  - `GET /candles/{symbol}` (query: `interval`, `since`, `until`)
  - `GET /public/last-trades`
  - `GET /public/order-book/{symbol}`
- `D:\Python-Codes\statanalyse\revbot_portfolio_monitor_extracted.txt` is OCR-style dashboard output, not a canonical API spec.
- Keep behavior decisions based on official Revolut X docs and use OCR text as symptom evidence.

## Organized Signals From Extracted File
- Repeated route/gate degradation:
  - `INSUFFICIENT ADVISORY`
  - `VOLATILITY INSUFFICIENT`
  - `Inputs C:N S:N P:N`
- Advisory radar repeatedly reports insufficient points:
  - `Observed X points, need at least 10 for radar`
- Outcome profile in sample window:
  - very low execution frequency
  - high hold/blocked ratio

## Root-Cause Summary In Current RevBot
1. Incremental sync symbols were tied to cycle-selected symbols rather than full scan universe.
2. Decision timeframe freshness was not guaranteed when timeframe lists/config drifted.
3. There was no dedicated per-symbol/per-timeframe ingestion freshness ledger.
4. ATR raw volatility could collapse to zero for quantized candle streams, triggering `insufficient_data`.

## Task Execution Ledger (Tasks 1-12)

### Completed (1-4)
1. Decoupled sync symbol scope from decision cycle scope (`scan` / `cycle` / `scan_plus_open`).
2. Enforced decision timeframe inclusion in sync timeframes and scheduler path.
3. Added ingestion freshness ledger with per-symbol/per-timeframe ages, lag intervals, stale flags, and decision-timeframe stale symbol list.
4. Hardened ATR computation to use non-zero return deltas when available (reduces false `atr_raw=0` on quantized symbols).

### Completed (5-8)
5. Refreshed behavior-lock baseline and added CI contract enforcement (`main.py`, `regime_router.py`, `strategy_engine.py` tracked + hash drift check).
6. Continued runtime split by moving sync-scope scheduling responsibility into runtime scheduler service and keeping `main.py` as thin delegator.
7. Tightened candle fallback policy for decision path:
   - scheduler now forwards decision-timeframe fallback overrides (`decision_use_public_fallback` / `decision_use_snapshot_fallback`)
   - non-decision timeframes keep base fallback policy (`allow_public_fallback` / `allow_snapshot_fallback`)
8. Promoted canonical endpoint profile after first success and validated OpenAPI-first request order:
   - canonical `GET /candles/{symbol}` is attempted first
   - cached known-good endpoint profile reuse retained

### Completed (9-12)
9. Converted router threshold handling to declarative typed profile tables and strategy-key mapping, preserving explicit config override compatibility.
10. Added deterministic/invariant router tests for gate reason-code precedence and randomized determinism checks.
11. Extended account-sync quote-cache coverage (bounded cache, stale/overflow eviction telemetry, TTL hit/miss behavior) and validated reduced repeat order-book pressure path.
12. Added/extended observability schema versioning compatibility:
   - decision-audit legacy schema inference reader
   - execution-report/trade-record legacy schema normalizers/readers
   - tests for backward-compatible schema inference.

## Validation Summary
- Focused test runs completed for the above changes, including router/config/account-sync/observability and replay integration suites.
- Replay suite (decision -> risk -> execution path coverage) passed in this pass.

## Remaining Data-Quality Follow-Ups
1. Add stronger endpoint pinning policy controls (reuse known-good endpoint profile until TTL/failure signal).
2. Continue tightening decision-critical fallback policy to avoid permissive data-path drift.
