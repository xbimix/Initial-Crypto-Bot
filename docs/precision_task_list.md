# RevBot Precision Task List

Last updated: 2026-04-02

## Objective
Maximize long-run profitability while reducing or not increasing risk by:
- improving decision precision,
- reducing stale capital lock-up,
- keeping downside regimes in observe-only behavior,
- preserving strict route quality and data readiness gates.

## Continuous Tracking Rules
1. Keep this list updated when any strategy/risk/routing file changes.
2. Promote only tasks with measurable impact (PnL quality, drawdown control, stale capital reduction, data integrity).
3. Every tuning change must include:
   - rationale,
   - risk assessment,
   - test coverage,
   - rollback path.

## File-by-File Task Tracker

| File | Current Observation | Improvement Task | Profit / Success Opportunity | Risk Impact | Status |
|---|---|---|---|---|---|
| `crypto_bot/strategy/regime.py` | New 8-regime detector active | Keep threshold calibration tied to live diagnostics (`confidence`, `fallback` mix) | Better route selection quality | Lower false routing risk | Done (baseline) |
| `crypto_bot/strategy/regime_engine.py` | Shadow stabilization intact | Monitor anti-flip responsiveness vs delayed reaction | Higher regime continuity | Lower churn risk | Done (baseline) |
| `crypto_bot/strategy/regime_engine_v2.py` | Raw regime now primary | Add periodic confidence calibration review from live outcomes | More actionable AUTO routing | No added entry looseness if gated | In progress |
| `crypto_bot/strategy/regime_router.py` | Observe-only for downside/choppy/unknown | Maintain strict no-backdoor-to-MR for defensive regimes | Avoid low-quality trades | Lower downside exposure | Done (baseline) |
| `crypto_bot/strategy/trend_pullback.py` | Route-local gates strengthened | Tune extension and weakening thresholds from route expectancy | Better trend entries | Lower late-entry risk | In progress |
| `crypto_bot/strategy/breakout_momentum.py` | Breakout gates strengthened | Tune retest + late-entry controls by symbol cluster | Better breakout timing | Lower exhaustion-entry risk | In progress |
| `crypto_bot/strategy/scoring.py` | Regime-aware scoring enabled | Keep no-trade regimes blocked from generic MR score path | Cleaner buy quality | Lower false positives | Done (baseline) |
| `crypto_bot/strategy/sell_eval.py` | Added stale position risk-release logic | Monitor release reason frequency and post-release redeploy outcomes | Capital recycling from stale trades | Lower stale exposure risk | Done (new) |
| `crypto_bot/strategy/strategy_orchestrator.py` | Added stale-exit config wiring | Continue tightening buy/sell telemetry for route-level attribution | Higher tuning precision | Lower hidden state drift | In progress |
| `crypto_bot/utils/config_schema.py` | Added schema for stale-exit keys | Add guardrails docs for conservative/aggressive profiles | Safer operator tuning | Lower config error risk | Done (new) |
| `crypto_bot/strategy/route_quality.py` | Quality gates active | Added rolling gate-health report (promotion/block reasons/readiness/freshness) | Better route throughput tuning | Lower overfitting risk | Done (new) |
| `crypto_bot/tools/live_safety_tuning_report.py` | Uses sync + audit metrics | Add stale-capital + route expectancy + stale-release attribution sections | Faster tuning feedback loop | Lower blind tuning risk | Done (upgraded) |
| `crypto_bot/tools/profit_profile_rollout.py` | Phase rollout helper available | Added guarded profile switch (`conservative/balanced/aggressive`) with preview-first flow | Safer staged tuning and reduced accidental risk jumps | Lower operator error risk | Done (new) |
| `crypto_bot/tools/regime_confidence_recalibration_report.py` | Weekly regime confidence analytics missing | Added advisory weekly confidence recalibration report from realized outcomes | Better confidence-threshold tuning quality | Lower over/under-filtering risk | Done (new) |
| `crypto_bot/tools/profit_profile_verify.py` | Post-apply drift checks were manual | Added 12h/24h SLO drift verification command with pass/fail checks | Faster, safer profile promotion decisions | Lower rollout regression risk | Done (new) |
| `crypto_bot/reporting/daily_summary.py` | Rich metrics available | Added route-level capital lock-up, stale-redeploy attribution, and closed-trade MAE/MFE approximation | Better profit bottleneck visibility | Lower stale and hidden downside risk | Done (new) |
| `crypto_bot/tests/test_strategy_regression.py` | Extended with stale-exit tests | Keep adding regression tests for each new tuning guard | Safer iteration speed | Lower regression risk | Done (updated) |
| `crypto_bot/tests/test_regime_router.py` | Updated to new canonical routing | Add explicit live-like AUTO tests for partial-quality advisory | Better confidence in AUTO behavior | Lower accidental rerouting risk | In progress |

## Immediate Tuned Settings (Now Implemented)
- `profit_locks.stale_exit_max_hold_seconds`: defaulted to `21 days` (conservative)
- `profit_locks.stale_exit_min_pnl_pct`: defaulted to `0.003` (0.3%)
- Exit reason: `stale_position_risk_release`

## Next High-Impact Tasks
1. Add route-level MAE/MFE to weekly aggregation (`weekly_summary`) so trend shifts are visible in one weekly panel.
2. Add controlled AUTO confidence backtests using replay fixtures before applying recalibration suggestions live.
3. Add post-apply verifier thresholds for route-level expectancy drift, not only freshness/rejection metrics.
