# Regime Source Contract

This document defines precedence and fallback for regime/routing inputs in RevBot strategy orchestration.

## Source precedence (AUTO mode)

1. `snapshot.regime_advisory` (if required fields present)
2. Runtime `evaluate_regime_unified(...)` advisory
3. Shadow-state advisory fallback (when configured)
4. Legacy `detect_regime(...)` context fallback inside V2 only for insufficient/low-confidence cases

## Required advisory fields for router readiness

- Suggested regime (`suggestedRegime` or equivalent)
- Confidence score (`confidenceScore` or equivalent)
- Data quality status
- Core key-window support (`supportedKeyWindows` / `supported_key_windows`)

Missing core key-window support is treated as `False` by the router.

## Route decision contract

- Manual configured regime always overrides AUTO.
- AUTO can route away from mean reversion only when confidence/stability/persistence and data gates pass.
- If any required gate fails, fallback route is `mean_reversion` with explicit fallback reason.

## Persistence contract

- Route/regime metadata maps are maintained through `strategy/route_metadata.py`.
- `strategy_engine.py` remains the orchestrator and delegates map update/payload injection to route metadata helpers.
