# Execution Model

## Overview
Paper execution now runs through an explicit simulator layer in `crypto_bot/execution/simulator.py`.

Core concepts:
- `OrderIntent`: execution request (`side`, `symbol`, quoted price, requested size, liquidity role).
- `ExecutionContext`: market microstructure context (spread, bid/ask, microprice, imbalance, momentum, quality, timeout policy).
- `Fill`: realized fill details.
- `ExecutionReport`: structured execution outcome with status, expected vs effective fill price, fee/slippage/latency, fill ratio, and reason.

## Modeled effects
- Taker and maker fees (`taker_fee_bps`, `maker_fee_bps`).
- Spread-aware expected fill price (bid/ask-aware).
- Slippage from spread, imbalance, momentum, participation pressure, and latency.
- Latency impact and timeout handling.
- Partial fills and liquidity-pressure rejections.
- Explicit rejection/cancel/timeout outcomes.

## Integration
- `PaperBroker` keeps existing external API (`buy`, `sell`, `preview_execution_cost_bps`) but delegates simulation to `ExecutionSimulator`.
- Trade rows now persist richer execution metadata, including:
  - `quoted_price`
  - `expected_fill_price`
  - `effective_fill_price`
  - `fee_usd`
  - `slippage_bps`
  - `latency_ms`
  - `fill_ratio`
  - `fill_reason`
  - `liquidity_role`

## PnL
- Sell-side realized PnL is net of entry fee allocation, exit fee, and simulated fill effects.
- Daily reporting includes route/strategy execution observability summaries net of fees/slippage.
