# RevBot Refactor Plan

## Current Architecture Summary
- Entry points:
  - `crypto_bot/main.py` runs the core bot loop (data sync, signal evaluation, risk gating, execution dispatch, audit writes).
  - `crypto_bot/control/control_server.py` exposes Flask control and mutating endpoints for runtime config/state operations.
  - `crypto_bot/control/run_control.py` launches control server.
- Execution flow:
  - `strategy.strategy_engine.evaluate_symbol(...)` creates decision payloads.
  - `trading.executor.Executor.handle_decision(...)` applies gating and delegates to paper execution.
  - `paper.paper_broker.PaperBroker` mutates balances/positions and writes trade records.
- Risk checks:
  - `risk.risk_manager.RiskManager` enforces cooldowns, exposure caps, daily-loss controls, and position sizing.
- State persistence/control surfaces:
  - JSON/JSONL state is persisted under `crypto_bot/state` via `utils.state_storage` and direct file I/O in some modules.
  - API routes in `control_server.py` read/write paper state, strategy state, and trades directly.

## Main Risks
1. Runtime-state coupling:
- Multiple modules directly hardcode `crypto_bot/state` or relative `state/` paths.
- Runtime artifacts are mixed into tracked source tree, increasing accidental commit risk.

2. Execution realism consistency:
- Paper execution currently includes slippage/fees/partials/timeouts, but logic is tightly embedded in `PaperBroker` and lacks a clean execution simulator contract.

3. Sizing contract fragility:
- Position sizing is risk-aware but returns a scalar float, obscuring rejection reasons/caps and reducing observability and safety.

4. Orchestration coupling:
- `main.py` and `control_server.py` are large and own many concerns (runtime, scheduling, housekeeping, diagnostics, safety).

5. Observability gaps:
- Decision and execution metadata are partly captured but not uniformly schema-driven across all outcomes.

## Planned Phases
1. Baseline and safety guardrails (complete in this phase): test baseline + architecture/refactor plan.
2. Runtime-state isolation:
- Introduce central runtime data root resolver (`BOT_DATA_DIR` + fallback support).
- Route state consumers through helper and preserve backward-compatible reads.
- Update `.gitignore` and add migration note/tests.
3. Execution simulation layering:
- Add explicit execution models (`OrderIntent`, `ExecutionReport`, `Fill`, `ExecutionContext`) and simulator service.
- Keep existing broker API but route internals through simulator.
4. True risk-based sizing contract:
- Replace scalar sizing with typed sizing result object and stop-distance-first risk budget logic.
- Enforce caps and preserve legacy config modes.
5. Runtime decoupling:
- Extract orchestration services from `main.py` along existing domain boundaries.
6. Decision vs execution observability:
- Standardize machine-readable attempt/result schema and route/strategy net metrics.
7. Config validation + fail-safes:
- Strengthen schema validation for sizing/execution/path safety.
8. Tests/docs/CI updates:
- Add focused and integration-style tests plus docs for execution, sizing, and runtime architecture.

## Behavior-Preservation Constraints
- Preserve existing entry points and API shapes unless explicitly versioned.
- Keep strategy decision behavior unchanged unless a documented risk/safety correction is required.
- Maintain backward compatibility for existing config keys with defaults/migrations.
- Keep current paper broker external methods usable (`buy`, `sell`, `preview_execution_cost_bps`, state refresh semantics).
- Require tests for every meaningful behavioral change and keep risk-sensitive changes explicit in notes.
