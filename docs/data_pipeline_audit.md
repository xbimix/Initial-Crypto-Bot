# Data Pipeline Audit (Phase 1)

Date: 2026-04-09 (UTC)
Scope: **Audit only** (no strategy/routing/threshold changes)
Runtime root examined: `.runtime/state/`

## 1) Candle Fetch Path Audit (Revolut API -> Ingestion)

### Code path inspected
- `crypto_bot/data/revolut_candle_fetcher.py`
- `crypto_bot/data/revolut_incremental_sync.py`
- `crypto_bot/data/live_sync_scheduler.py`

### Endpoint/parameter behavior confirmed
- Canonical private endpoint candidate is used first: `/candles/{symbol}`.
- Request params include:
  - `interval` (minutes)
  - `since` (ms preferred, with seconds/ISO fallbacks)
  - `until` (ms preferred, with seconds/ISO fallbacks)
- Windowing guard is enabled:
  - `MAX_CANDLES_PER_REQUEST = 1000`
  - oversized ranges are split via `_iter_request_windows(...)`
- Fallback policy exists (config-driven):
  - public fallback optional
  - snapshot-derived candle fallback optional

### OpenAPI reference cross-check (local)
- `crypto_bot/api/revolut-x.yml`
- `crypto_bot/api/revolut-x.json`
- Both include canonical candle operation: `/candles/{symbol}` with `interval`, `since`, `until`.

### Runtime telemetry observed
From `.runtime/state/market_sync_health.json` at audit time:
- `endpoint_telemetry.fetch_calls`: 18,396
- `success_calls`: 18,396
- `failed_calls`: 0
- `official_success_calls`: 18,396
- `public_success_calls`: 0

Interpretation: current runtime is successfully hitting official signed candle endpoints.

## 2) 1m Candle Age Check (Sampled Symbols)

Expected decision timeframe cadence target: 60s bars (practical fresh window generally <=60-90s, scheduler-dependent).

### Universe stats (1m)
- Symbols in DB (1m): 77
- Age distribution (`now - latest candle close`):
  - min: 46.9s
  - p50: 166.9s
  - p90: 226.9s
  - p99: 286.9s
  - max: 286.9s
- `>120s`: 47 symbols
- `>300s`: 0 symbols

### 10-symbol sample (freshest + stalest)
| Symbol | Latest candle age (s) |
|---|---:|
| BNB-USD | 46.9 |
| GMT-USD | 46.9 |
| HBAR-USD | 46.9 |
| HFT-USD | 46.9 |
| HYPE-USD | 46.9 |
| MLN-USD | 286.9 |
| POL-USD | 286.9 |
| SUI-USD | 286.9 |
| XLM-USD | 286.9 |
| ZK-USD | 286.9 |

Interpretation: candles are updating, but many symbols are multiple minutes old versus 1m ideal freshness.

## 3) Storage Integrity Audit (SQLite)

DB: `.runtime/state/market_data.db`
- `PRAGMA quick_check`: `ok`
- Tables: `candles`, `sync_state`, `orderbook_snapshots`

### Integrity checks
- Duplicate key rows (`symbol,timeframe,open_time`): **0**
- Non-positive OHLC rows: **0**
- `high < low` violations: **0**
- 1m step continuity (last 500 bars per symbol):
  - symbols with gaps: **0 / 77**
  - global avg step: **60,000 ms**

### Notable storage characteristic
- `close_time` is mostly null in stored rows (timeframe-dependent, near 100% for most TFs).
- Runtime compensates by estimating close time from `open_time + interval`.

Interpretation: storage is structurally healthy and not the primary break point.

## 4) Ingestion Frequency / Throughput Audit

### Scheduler cadence (last 180 health-history rows)
Source: `.runtime/state/market_sync_health_history.jsonl`
- Avg cycle interval: **16.23s**
- Max cycle interval: **18.47s**
- Avg requests/cycle: **6**
- Avg new candles inserted/cycle: **26.7**
- Errors total: **0**

### Decision-timeframe servicing pressure
- Avg due decision jobs per cycle: **72**
- Avg selected decision jobs per cycle: **5**
- Selection ratio: **~6.94%** per cycle
- Scheduler report repeatedly shows large due backlog across TFs and many stale-catchup candidates.

### Sync-state age (1m)
- Rows: 77 (`status=ok` for all)
- p50 last-sync age: **129.8s**
- max last-sync age: **258.5s**

Interpretation: ingestion is active and error-free, but service capacity per tick is much lower than due workload.

## 5) Required Phase 1 Deliverables

### Fetch frequency
- Stable ~16s cycle, ~6 requests/tick, official candle endpoint success rate currently 100%.

### Candle age distribution
- 1m age p50 ~167s, p90 ~227s, max ~287s.

### Symbols with stale data
- Runtime freshness ledger indicates a large rotating set of stale decision-timeframe symbols each cycle (dozens).
- Example max-age symbols at audit snapshot include: `ACH-USD`, `ASM-USD`, `BIGTIME-USD`, `CVX-USD`, `DOGE-USD`, `FIL-USD`, `FLR-USD`, `IMX-USD`, `JASMY-USD`, `JUP-USD` (~258s).

### Symbols missing data
- 1m missing symbols in active universe: **0** (all 77 present).

### Ingestion bottlenecks
1. **Capacity mismatch / starvation pattern**
   - Due 1m jobs (~72) far exceed selected (~5) per cycle.
2. **Request budget constraint**
   - `max_sync_requests_per_tick=6` with multi-timeframe pressure leaves many 1m symbols aging.
3. **Cross-timeframe backlog pressure**
   - Background TFs remain heavily due; scheduler reports starvation in non-decision TFs and high stale-catchup candidate counts.

## Phase 1 Conclusion (Audit Only)

Primary observed failure mode is **ingestion servicing pressure** (not DB corruption, not endpoint failure, not duplicate/gap storage faults).

At audit time, data does not appear invalid/corrupt; it appears **under-served relative to symbol/timeframe workload**, causing many symbols to run at 2-5 minute candle age despite healthy API calls and healthy storage writes.
