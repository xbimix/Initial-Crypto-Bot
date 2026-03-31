# Runtime Architecture

## Entry points
- Bot runtime loop: `crypto_bot/main.py`
- Control/API server: `crypto_bot/control/control_server.py`

## Runtime state model
- Runtime data root uses `BOT_DATA_DIR` (default: `.runtime/`).
- State files resolve to `.runtime/state/` by default.
- Legacy fallback support remains for old state locations (`REVBOT_STATE_DIR` / `crypto_bot/state`).

## Orchestration boundaries
Main loop responsibilities are split across modules:
- Market + strategy decisioning: `strategy/*`, `data/*`
- Risk + execution dispatch: `trading/executor.py`, `risk/risk_manager.py`, `paper/paper_broker.py`
- Periodic orchestration helpers: `runtime/periodic.py`
  - heartbeat
  - account sync
  - universe sync
  - coverage logging
  - DB maintenance
  - housekeeping

## Observability
- Decision audit stream: `decision_audit.jsonl`
- Runtime events: `runtime_events.jsonl`
- Execution observability rollups in daily summary via `observability/metrics.py`.

## Safety controls
- Daily loss guard (pause/close-all).
- Market-quality buy gate (`risk.block_bad_market_quality`).
- Execution-failure kill-switch pause (`max_consecutive_execution_failures`, `execution_failure_pause_seconds`).
