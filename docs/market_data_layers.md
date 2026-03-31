# Market Data Layering

The runtime market-data path is now split into explicit layers while keeping legacy snapshot output compatible.

## Layer 1: Ingestion

Module: `crypto_bot/data/ingestion.py`

- Talks to exchange APIs only (`order_book`, `trades`).
- Normalizes symbols and numeric fields.
- Attaches source metadata (`received_ts_epoch`, `exchange_ts_epoch`, endpoint).
- Rejects malformed rows and invalid values.
- Outputs typed updates: `OrderBookUpdate`, `TradeUpdate` (plus `TickerUpdate`/`CandleUpdate` contracts for extension).

## Layer 2: Symbol State Store

Module: `crypto_bot/data/state_store.py`

- Canonical per-symbol in-memory state.
- Maintains snapshot versions and per-field update timestamps.
- Caches stream history, candle series, and indicator cache entries.
- Exposes read-only result objects and legacy-compatible maps.

## Layer 3: Feature Engine

Module: `crypto_bot/data/feature_engine.py`

- Computes derived indicators.
- Uses versioned fingerprints to avoid full recomputation when source state has not changed.
- Supports incremental behavior:
  - unchanged candle `latest_open_time` => cache hit
  - new candle version => recompute

## Layer 4: Decision Input Builder

Module: `crypto_bot/data/decision_input_builder.py`

- Builds a validated `DecisionContext` from market snapshot payloads.
- Enforces strategy evaluation gate before strategy invocation.
- Emits explicit blocked reasons and audit fields.

## Layer 5: Persistence and Replay

Module: `crypto_bot/data/replay_persistence.py`

- Append-only JSONL replay log hooks.
- Captures:
  - normalized ingestion events
  - snapshot-change events
  - decision-context events
- Disabled by default; enable with:
  - `market_data.replay_log_enabled: true`
  - optional `market_data.replay_log_filename`

## Compatibility Notes

- `fetch_market_snapshot` still returns the legacy snapshot dict shape, with extra metadata:
  - `snapshot_version`
  - `snapshot_field_timestamps`
  - `data_quality_state`
  - `strategy_eval_gate`
  - `strategy_eval_allowed`
