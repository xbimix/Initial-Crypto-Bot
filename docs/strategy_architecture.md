# Strategy Architecture (Frozen Baseline)

This document freezes the current strategy architecture and module ownership for refactor safety.

## Core ownership

- `crypto_bot/strategy/regime_engine_v2.py`
  - Primary regime engine.
  - Produces the main multi-timeframe regime advisory used by AUTO routing.

- `crypto_bot/strategy/regime_router.py`
  - Route selector.
  - Chooses effective route/strategy from configured regime plus advisory + gating signals.

- `crypto_bot/strategy/regime_engine.py`
  - Shadow stability layer.
  - Handles confirmations/cooldown anti-flap persistence for regime continuity.

- `crypto_bot/strategy/regime.py`
  - Legacy fallback detector only.
  - Used only when V2 advisory is unavailable/invalid or below confidence threshold.

- `crypto_bot/strategy/strategy_engine.py`
  - Thin orchestration entrypoint only.
  - Delegates decision flow to orchestrator/runtime modules.

## Target decision flow

`regime_engine_v2 -> regime_engine (shadow/stability) -> regime_router -> route evaluator`

Legacy `regime.py` must not compete with V2 during normal flow; it is fallback-only.

## Position contract rule

Open positions keep:

- `entry_route`
- `entry_regime`
- `exit_policy`

These are not remapped mid-trade unless explicitly designed and gated.
