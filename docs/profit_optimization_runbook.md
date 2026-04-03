# Profit Optimization Runbook (Low-Failure Profile)

Date: 2026-04-02  
Scope: derived from `docs/*` architecture/risk/execution docs plus live baseline snapshot.

## 1) Baseline Summary (Current Runtime)

Source file: `docs/profit_baseline_2026-04-02.json` (generated from `.runtime/state` over 168h window).

- Sync/data quality:
  - `fresh_1h_median=0`, `fresh_4h_median=0`, `fresh_24h_median=0`
  - `degraded_jobs_per_hour=15.655` (very high)
  - `rate_limited_events_per_hour_proxy=0.825` (not the main bottleneck)
- Trading activity:
  - `trade_rows_window=1` (very low recent execution throughput)
  - `realized_total.closed_parts_total=56`
  - `mean_reversion win_rate=94.55%`, `expectancy=$5.27/part`, `median_hold=30.5h`
- Runtime/capital:
  - `open_positions=22`
  - `stale_release_candidates=0`

Primary blocker to reliable profit scaling is data freshness/degraded sync, not lack of strategy routes.

## 2) Computed Structural Priorities

Based on docs and inventory:

1. Data integrity before signal quality:
  - `market_data_layers.md` and `runtime_architecture.md` make strategy evaluation quality-gated.
  - With zero fresh candles, expected behavior is HOLD-heavy and unreliable entries.
2. Risk/size hardening before scaling:
  - `risk_sizing.md` shows stop-distance sizing + caps is the lowest-failure path.
3. Execution realism must be enabled:
  - `execution_model.md` contracts are only fully effective when `paper_execution.enabled=true`.
4. Runtime safety remains hard constraint:
  - Daily loss and consecutive-failure pauses should remain strict.

## 3) Target Operating Profile (Most Robust from Current Design)

This profile optimizes risk-adjusted expectancy, not raw trade count.

1. Trade only on quality-approved decisions.
2. Keep downside/choppy/unknown regimes in observe-only behavior.
3. Use stop-distance-aware sizing with explicit risk budget.
4. Cap portfolio/symbol/notional exposure hard.
5. Use conservative execution assumptions and evaluate net expectancy after costs.
6. Keep runtime kill-switches strict (daily loss + consecutive failure pause).

## 4) Step-by-Step Execution Plan

## Step 0 - Safety Snapshot and Rollback Point

1. Copy current runtime config:
   - `.runtime/state/config.json` -> `.runtime/state/config.backup.2026-04-02.json`
2. Store current baseline report:
   - already saved at `docs/profit_baseline_2026-04-02.json`

Pass condition:
- Backup exists and JSON validates.

## Step 1 - Data Quality First (No Risk Increase)

Update config keys:

1. `market_data.source_map.candles.allow_snapshot_fallback = false`
2. `market_data.source_map.candles.decision_use_snapshot_fallback = false`
3. `market_data.freshness_slo.min_fresh_1h = 1`
4. `market_data.freshness_slo.min_fresh_4h = 1`
5. `market_data.freshness_slo.max_degraded_jobs = 1` (non-zero but strict)
6. `market_data.route_quality_guard_enabled = true`
7. `market_data.route_quality_min_confidence = 78`
8. `market_data.route_quality_min_stability = 65`
9. `market_data.route_quality_min_persistence = 65`

Why:
- Forces entries to depend on valid fresh data and stronger route quality.

Pass condition after 6-12h:
- `fresh_1h_latest >= 1`
- `degraded_jobs_per_hour <= 2.5`
- No increase in runtime safety pauses.

Rollback trigger:
- If `trade_rows_window=0` for 12h and freshness remains failed, restore backup and investigate ingestion/sync path before any tuning.

## Step 2 - Execution Realism and Fill Safety

Update config keys:

1. `paper_execution.enabled = true`
2. `paper_execution.base_slippage_bps = 4.0`
3. `paper_execution.max_slippage_bps = 80.0`
4. `paper_execution.soft_spread_bps = 30.0`
5. `paper_execution.hard_reject_spread_bps = 180.0`
6. `paper_execution.min_fill_ratio = 0.35`
7. `paper_execution.reject_if_fill_ratio_below = 0.15`
8. `paper_execution.enable_timeouts = true`
9. `paper_execution.timeout_ms = 2000`

Why:
- Removes optimistic fills and prevents low-quality execution from polluting expectancy.

Pass condition after 24h:
- Median slippage and fee fields appear in new trades.
- Rejection rate is stable (not runaway).
- Net expectancy (after costs) stays positive.

Rollback trigger:
- If valid opportunities are rejected excessively and net expectancy collapses for 24h.

## Step 3 - Risk Sizing and Exposure Limits

Update config keys:

1. `risk.sizing_mode = "auto"`
2. `risk.risk_percent = 0.01`
3. `risk.max_loss_per_trade_usd = 40`
4. `risk.trade_amount_usd = 150` (legacy fallback path)
5. `risk.max_concurrent_trades = 12`
6. `risk.max_concurrent_trades_per_token = 1`
7. `risk.max_trade_amount_usd = 750`
8. `risk.max_notional_usd = 750`
9. `risk.max_portfolio_exposure_pct = 65`
10. `risk.max_exposure_per_token_pct = 12`
11. `risk.min_trade_notional_usd = 25`
12. `risk.liquidity_cap_notional_usd = 500`
13. `risk.block_bad_market_quality = true`

Why:
- Converts to bounded-risk behavior and prevents concentration blowups.

Pass condition after 24-48h:
- No single-symbol concentration events.
- Daily drawdown profile improves.
- Expectancy per closed part remains positive.

Rollback trigger:
- If throughput drops too far with no drawdown benefit.

## Step 4 - Runtime Kill-Switch Hardening

Update config keys:

1. `risk.daily_loss_limit_usd = 150`
2. `risk.daily_loss_auto_pause = true`
3. `risk.daily_loss_close_all = false`
4. `risk.max_consecutive_execution_failures = 3`
5. `risk.execution_failure_pause_seconds = 300`

Why:
- Stops bad sessions early and prevents repeated failure spirals.

Pass condition:
- Safety events are explicit in runtime events and no state corruption appears.

## Step 5 - Capital Efficiency Review (Stale Release)

Keep current defaults first:

1. `profit_locks.stale_exit_max_hold_seconds = 1814400` (21 days)
2. `profit_locks.stale_exit_min_pnl_pct = 0.003`

Then adjust only if metrics justify:

1. If stale lock-up increases with low redeploy quality, do not tighten.
2. If stale lock-up is high and redeploy outcomes are positive, trial:
   - `stale_exit_max_hold_seconds = 1209600` (14 days)
   - keep `stale_exit_min_pnl_pct = 0.003`

## 5) Validation and Test Gate

Run after each step:

1. `python crypto_bot/tools/live_safety_tuning_report.py --state-dir .runtime/state --hours 12`
2. `python -m pytest crypto_bot/tests/test_runtime_safety_service.py -q`
3. `python -m pytest crypto_bot/tests/test_paper_execution_realism.py -q`
4. `python -m pytest crypto_bot/tests/test_risk_manager.py -q`
5. `python -m pytest crypto_bot/tests/test_market_layers.py -q`
6. `python -m pytest crypto_bot/tests/test_market_state_store.py -q`

Full gate before promoting profile:

1. `scripts/check_local.ps1 -SkipWebBuild`

## 6) Promotion Criteria (Go/No-Go)

Promote only if all are true over at least 48h:

1. Net expectancy remains positive.
2. Drawdown does not increase versus baseline.
3. Freshness/quality gates remain passing.
4. Runtime pause/failure events do not trend upward.
5. No symbol concentration breaches.

If any fail, rollback to previous config snapshot and re-run baseline.

## 7) Guarded Profile Switch Commands

Use `crypto_bot/tools/profit_profile_rollout.py` for preview-first profile switching.

1. Preview balanced profile (no config write):
   - `python crypto_bot/tools/profit_profile_rollout.py --state-dir .runtime/state --profile balanced --print-json`
2. Apply balanced profile from conservative (explicit upshift approval):
   - `python crypto_bot/tools/profit_profile_rollout.py --state-dir .runtime/state --profile balanced --apply --allow-risk-upshift --print-json`
3. Apply aggressive profile directly from conservative (requires jump flag):
   - `python crypto_bot/tools/profit_profile_rollout.py --state-dir .runtime/state --profile aggressive --apply --allow-risk-upshift --allow-profile-jump --print-json`

Safety behavior:
- `--profile` without `--apply` is preview-only.
- Risk upshifts are blocked unless `--allow-risk-upshift` is provided.
- Multi-level upshifts are blocked unless `--allow-profile-jump` is also provided.

## 8) Post-Apply Verification and Recalibration Commands

1. Verify post-apply SLO drift over 12h/24h windows:
   - `python crypto_bot/tools/profit_profile_verify.py --state-dir .runtime/state --windows 12,24 --print-json`
2. Verify relative to explicit apply timestamp:
   - `python crypto_bot/tools/profit_profile_verify.py --state-dir .runtime/state --reference-ts <apply_ts_epoch> --windows 12,24 --print-json`
3. Generate weekly regime-confidence recalibration guidance (advisory only):
   - `python crypto_bot/tools/regime_confidence_recalibration_report.py --state-dir .runtime/state --days 7 --min-closed-parts 6`

Operational rule:
- Treat recalibration output as advisory and apply changes only after replay/backtest checks and a new verification window.
