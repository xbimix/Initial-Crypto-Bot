# RevBot vs BinanceBot Side-by-Side Diff + 24h Baseline

Generated at: `2026-04-18 08:08:59` (local runtime clock)

## Scope

- RevBot active config: `D:\Python-Codes\RevBot\.runtime\state\config.json`
- BinanceBot reference config: `D:\Python-Codes\BinanceBot\BinanceBot-binance\crypto_bot\state\config.json`
- Log windows:
  - Strict last 24h from now: `2026-04-17 08:08:59` -> `2026-04-18 08:08:59`
  - Anchored 24h: last available 24h ending at each bot's latest strategy/runtime timestamp

## Side-by-Side Key Diff

| Key | RevBot Active | Binance Reference |
|---|---:|---:|
| `symbols_count` | `17` | `62` |
| `risk.signal_confirmation_cycles` | `2` | `2` |
| `volatility_filters.min_atr` | `0` | `0` |
| `volatility_filters.min_atr_pct` | `0` | `0` |
| `market_data.trade_confirmation_limit` | `100` | `100` |
| `market_data.max_symbols_per_cycle` (vs Binance pipeline equivalent) | `40` | `40` |
| `market_data.max_sync_requests_per_tick` (vs Binance pipeline equivalent) | `24` | `240` |
| `market_data.sync_reserved_requests_decision_timeframe` (vs Binance per-symbol equivalent) | `8` | `6` |
| `market_data.sync_max_background_share` | `0.6` | n/a |
| `market_data.route_quality_guard_enabled` | `false` | n/a |
| `market_data.route_quality_min_confidence` | `68` | n/a |
| `market_data.route_quality_min_stability` | `55` | n/a |
| `market_data.route_quality_min_persistence` | `55` | n/a |
| `market_data.strategy_eval_min_quality_score` | `0.55` | n/a |
| `market_data.strict_strategy_eval_gate_enabled` | `false` | n/a |
| `market_data.strategy_allow_partial_participation` | `true` | n/a |
| `market_data.source_map.candles.decision_use_public_fallback` | `true` | n/a |
| `strategy_defaults.router.auto_use_route_quality_gates` | `false` | n/a |
| `strategy_defaults.router.auto_min_confidence` | `68` | `68` |
| `strategy_defaults.router.auto_min_stability` | `55` | `55` (route-contract default) |
| `strategy_defaults.router.auto_min_persistence` | `55` | `55` (route-contract default) |
| `strategy_defaults.router.auto_trend_min_confidence` | `68` | lower trend threshold in route contract (`62`) |
| `strategy_defaults.router.auto_breakout_min_confidence` | `72` | `72` (route-contract default) |
| `strategy_defaults.tuning_profile` | `balanced` | n/a |

## RevBot Active Universe and Tiering

### `symbols` (17)

`BTC-USD`, `ETH-USD`, `SOL-USD`, `BNB-USD`, `XRP-USD`, `ADA-USD`, `LINK-USD`, `DOGE-USD`, `DOT-USD`, `AVAX-USD`, `NEAR-USD`, `ONDO-USD`, `FIL-USD`, `TRX-USD`, `TIA-USD`, `SUI-USD`, `BIGTIME-USD`

### `market_data.symbol_tiers`

- `tier1`: `BTC-USD`, `ETH-USD`, `SOL-USD`, `BNB-USD`, `XRP-USD`, `ADA-USD`, `LINK-USD`, `DOGE-USD`
- `tier2`: `DOT-USD`, `AVAX-USD`, `NEAR-USD`, `ONDO-USD`, `FIL-USD`, `TRX-USD`, `TIA-USD`, `SUI-USD`
- `tier3`: empty

## Strict Last-24h Snapshot (From "Now")

Window: `2026-04-17 08:08:59` -> `2026-04-18 08:08:59`

### RevBot

- Latest strategy ts: `2026-04-05 00:08:18`
- Latest trade ts: `2026-04-04 20:58:31`
- Latest runtime ts: `2026-04-05 00:08:27`
- Strategy actions in strict window: `BUY 0 / SELL 0 / HOLD 0`
- Trade executions in strict window: `BUY 0 / SELL 0`

### BinanceBot

- Latest strategy ts: `2026-03-30 20:13:30`
- Latest trade ts: `2026-03-30 18:42:11`
- Latest runtime ts: `2026-03-30 20:13:30`
- Strategy actions in strict window: `BUY 0 / SELL 0 / HOLD 0`
- Trade executions in strict window: `BUY 0 / SELL 0`

## Anchored Last-Active 24h Snapshot

### RevBot anchored window

- Window: `2026-04-04 00:08:18` -> `2026-04-05 00:08:18`
- Strategy actions: `BUY 0 / SELL 0 / HOLD 5445`
- Trade executions: `BUY 0 / SELL 0`
- Runtime blockers:
  - `market_data_quality:stale = 2026`
  - `core_not_ready = 5`
  - `buy_blocked_signal_confirmation = 0`
- Top HOLD reasons:
  - `insufficient_data = 2280`
  - `atr_too_low = 803`
  - `waiting_for_first_lock = 533`
  - `scalper_momentum_not_ready = 455`
  - `price_below_buy_zone = 375`
  - `score_below_threshold = 325`

### BinanceBot anchored window

- Window: `2026-03-29 20:13:30` -> `2026-03-30 20:13:30`
- Strategy actions: `BUY 296 / SELL 44 / HOLD 11131`
- Trade executions: `BUY 113 / SELL 32`
- Runtime blockers:
  - `market_data_quality:stale = 0`
  - `core_not_ready = 0`
  - `buy_blocked_signal_confirmation = 104`
- Top decision reasons:
  - `price_above_buy_zone = 3933`
  - `waiting_for_first_lock = 3360`
  - `warming_up_history = 1120`
  - `price_below_buy_zone = 959`
  - `in_position = 749`
  - `insufficient_volatility_stretch = 520`

## Readout

- RevBot parity changes are in place for P0 gate relaxation and throughput.
- Strict current 24h has no new activity (both bots have stale logs relative to current date).
- Last active RevBot window remains blocked by stale/insufficient data pathing; last active Binance window shows normal execution throughput.
