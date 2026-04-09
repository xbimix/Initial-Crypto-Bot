# Implementation Checklist: Tasks 9-12

This checklist tracks the current execution pass for tasks 9-12.

## Task 9: Declarative Router Threshold Profiles
- [x] Add typed profile contracts for router threshold defaults.
- [x] Replace strategy threshold branching with declarative key maps and typed profile lookups.
- [x] Keep explicit router config overrides backward-compatible.
- [x] Preserve existing AUTO fallback behavior for unchanged configs.
- [x] Run router parity tests and strategy regression tests.

## Task 10: Router Invariant / Property Tests
- [x] Add deterministic precedence tests for early safety gates.
- [x] Add randomized invariant tests for reason-code determinism under mixed failing conditions.
- [x] Validate full router test suite passes.

## Task 11: Account-Sync Quote Cache Enhancements
- [x] Verify bounded quote cache + stale/overflow eviction telemetry is present.
- [x] Add/extend tests for stale eviction telemetry and cache hit/miss behavior.
- [x] Verify order-book call reduction remains intact under TTL cache.

## Task 12: Observability Schema Versioning + Backward-Compatible Readers
- [x] Add decision-audit reader that infers schema for legacy rows.
- [x] Add execution-report/trade-record normalizers for legacy schema inference.
- [x] Add tests for backward-compatible schema inference and structured version fields.
- [x] Run targeted observability tests.

## Final Verification
- [x] Run focused test matrix for tasks 9-12.
- [x] Summarize behavior-sensitive changes and any compatibility notes.
