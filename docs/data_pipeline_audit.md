# Data Pipeline Audit (Phase 1, No Code Changes)

Date: 2026-04-08  
Mode: Forensic audit only (no strategy/routing/threshold changes)

## Scope

This audit traces data flow across:

1. Revolut API candle fetch contract and request usage
2. Ingestion/scheduler cadence and request budget behavior
3. Storage integrity in SQLite (`candles`, `sync_state`)
4. Freshness and staleness distribution for 1m candles

## Ground Truth Sources

- OpenAPI references:
  - `crypto_bot/api/revolut-x.yml`
  - `crypto_bot/api/revolut-x.json`
- Runtime state:
  - `.runtime/state/market_data.db`
  - `.runtime/state/market_sync_health.json`
  - `.runtime/state/market_sync_health_history.jsonl`
  - `.runtime/state/bot.log`
- Implementation:
  - `crypto_bot/data/revolut_candle_fetcher.py`
  - `crypto_bot/data/revolut_incremental_sync.py`
  - `crypto_bot/data/live_sync_scheduler.py`
  - `crypto_bot/data/candle_coverage.py`

## 1) Fetch Contract Audit (Revolut vs RevBot)

### OpenAPI contract (`/candles/{symbol}`)

From `revolut-x.yml`:

- Path: `/candles/{symbol}`
- Query:
  - `interval` (minutes, enum includes 1/5/15/30/60/240/1440/2880/5760/10080/20160/40320)
  - `since` (epoch ms)
  - `until` (epoch ms)
- Note: if `since` omitted, API can return up to 5000 candles before `until`

From `revolut-x.json`:

- `symbol` is required path param
- `interval/since/until` match above

### RevBot implementation behavior

`revolut_candle_fetcher.py`:

- Uses canonical endpoint first (`/candles/{symbol}`) with ms and seconds variants.
- Supports official/public fallback candidates and path variants.
- Normalizes symbol (`/`/`_` -> `-`).
- Enforces local max-per-request windowing via `MAX_CANDLES_PER_REQUEST = 1000`.

`revolut_incremental_sync.py`:

- Uses incremental fetch (`since = latest_open + interval`) and chunks request windows.
- Request windows size = `interval_ms * MAX_CANDLES_PER_REQUEST`.

### Contract alignment summary

- Correct: uses documented `/candles/{symbol}`, `interval`, `since`, `until`.
- Conservative: local cap 1000 vs API note mentioning up to 5000 when `since` omitted.
- Risk: broad candidate probing still exists (many fallback endpoint shapes), though working-candidate cache reduces repeated probing after success.

## 2) Storage Integrity Audit

Active DB: `.runtime/state/market_data.db`

Tables present:

- `candles`
- `sync_state`
- `orderbook_snapshots`

`candles` schema contains expected OHLCV + timestamps:

- `symbol,timeframe,open_time,close_time,open,high,low,close,volume,source,updated_at`

Integrity checks (1m focus):

- Duplicate key rows (`symbol,timeframe,open_time`): **0**
- Recent gap checks (top 10 symbols, last 500 rows):
  - Mostly exact 60s spacing
  - Occasional 120s max gap on a minority (observed on SNX-USD/CVX-USD sample)

Conclusion: no evidence of DB corruption or duplication in active runtime DB.

## 3) Freshness Audit (1m)

### Current point-in-time (audit moment)

Across 77 symbols:

- p50 age: ~21604.5s
- p90 age: ~21724.5s
- p99 age: ~21724.5s
- max age: ~21724.5s
- `>120s`: 77/77
- `>300s`: 77/77

Interpretation: data is uniformly stale now because ingestion has not advanced since last runtime activity.

### Last active sync evidence (from runtime logs/history)

From `bot.log` / `market_sync_health_history` near last active window:

- Candle sync cycle interval: avg ~16.4s (min 15s, max 21s)
- Requests per cycle: fixed 6
- Errors: 0
- Decision timeframe oldest due age (`1m`): avg ~264s, max ~294s
- Decision freshness SLO reported as OK at that time

Interpretation: while running, ingestion was active and internally healthy under current SLO; current stale state reflects halted/idle ingestion since last run.

## 4) Ingestion Frequency / Bottleneck Audit

### Scheduler pressure (last 200 snapshots)

- `due_jobs_total` avg: ~423.1 (min 384, max 449)
- `selected_jobs_total` avg: **6.0**
- `sync.requests` avg: **6.0**
- Starvation frequency observed:
  - `1d`: 188
  - `15m`: 188
  - `5m`: 178
  - `1h`: 123
  - `4h`: 123

### Config/runtime context

- `market_data.max_sync_requests_per_tick = 6`
- `decision_candle_timeframe = 1m`
- `sync_timeframes = [1h,4h,1d,1m,5m,15m]`
- Universe size in coverage snapshot: 77 symbols

### Bottleneck evidence

The scheduler has structurally higher due-job demand than request capacity:

- Demand queue: ~384-449 due jobs
- Capacity per tick: 6 jobs
- This guarantees persistent backlog and recurring starvation of non-priority timeframes.

Primary bottleneck detected: **ingestion throughput under current request budget vs universe/timeframe workload**.

## 5) Symbol-level sample (1m)

Sampled top symbols showed:

- Continuous 60s cadence in stored rows (historical sequence quality is good)
- Latest-open ages currently ~21494-21674s (uniform stale due to runtime inactivity)

## 6) Additional Observations

- Active runtime source is `.runtime/state/*`; legacy `crypto_bot/state/*` still exists and can confuse manual audits if inspected accidentally.
- `market_sync_health.coverage.fresh_counts_by_timeframe` can look healthy for core TFs while `stale_symbol_timeframes` remains high, because stale counting includes broader symbol-timeframe combinations.

## 7) Phase 1 Conclusion

No evidence found of:

- DB corruption
- duplicate candle key explosion
- timestamp ordering breakage in sampled 1m data

Strong evidence found of:

- **Throughput mismatch / scheduler pressure** (high due queue vs fixed low request cap)
- **Current stale state caused by ingestion inactivity since last run**

Likely primary root-cause class (for low trade frequency episodes): **ingestion starvation under workload pressure**, especially when runtime is active but constrained by low request budget across many symbols/timeframes.

---

## Recommended Next Phase (Phase 2)

Proceed with `data_freshness_report.md` using rolling-window freshness distributions and explicit delay-ratio metrics:

- `candle_age_seconds` by symbol
- p50/p90/max while process is actively running
- `% symbols >2x` and `>5x` expected interval
- compare candle age vs scheduler oldest-due age

