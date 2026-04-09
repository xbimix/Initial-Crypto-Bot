# AGENTS.MD - RevBot Cleanup And Safety Protocol

## Purpose
This file defines strict rules for cleanup and reorganization work.

Primary goals:
- Keep runtime behavior stable.
- Remove or relocate junk safely.
- Make repository structure professional and maintainable.

All cleanup must be staged, reversible, and documented.

## Core Principles
### 1. Safety First
- Never delete or move files before classification.
- Never do repo-wide destructive cleanup in one pass.
- Always prefer `archive -> review -> delete`.
- If uncertain, mark `REVIEW` and keep.

### 2. Preserve Runtime Behavior
High-risk areas that require explicit approval before structural changes:
- `crypto_bot/` runtime logic, orchestration, scheduler, strategy, and risk code
- `web-ui/` app runtime behavior
- control/auth surfaces
- config loaders and state path helpers
- `.runtime/` live state files
- `.github/workflows/` CI
- active tests

### 3. Runtime Path Truth
- Canonical runtime root is `.runtime/state/`.
- Legacy `crypto_bot/state/` is migration fallback only.
- Never assume legacy state is active without path-resolution proof.

### 4. Classification Required
Every candidate file/folder must be labeled as one of:
- `CORE_RUNTIME`
- `ACTIVE_TEST`
- `CANONICAL_DOC`
- `HISTORICAL_DOC`
- `GENERATED_ARTIFACT`
- `LOG_OR_SNAPSHOT`
- `SCRIPT_OR_TOOL`
- `DUPLICATE_OR_SUPERSEDED`
- `UNKNOWN_REVIEW`

### 5. Archive Before Delete
- Confidence below high: archive only.
- Delete only after proving:
1. no import references
2. no test references
3. no CI references
4. no startup/runtime references
5. no script/config references

### 6. Small Reviewable Changes
- One cleanup category per commit.
- No mixed runtime + cleanup refactors in one commit.
- Every move/delete must be logged in a markdown report.

## Target Repository Structure
- `crypto_bot/` source runtime code and tests (`crypto_bot/tests/`)
- `web-ui/` UI source code
- `docs/` active docs
- `docs/archive/` historical docs and superseded plans
- `scripts/` operational scripts
- `artifacts/` generated reports, exports, extracted text, temporary outputs
- `.runtime/` runtime state (ignored by git, not deleted aggressively)

## Cleanup Phases (Strict Order)
### Phase 0 - Setup
- Work on a cleanup branch.
- Load this AGENTS protocol.
- No file changes yet.

### Phase 1 - Inventory (No Moves/Deletes)
Deliver under `docs/cleanup/`:
- `cleanup_inventory.md`
- `keep_manifest.md`
- `deletion_candidates.md`
- `move_plan.md`
- `risk_report.md`

### Phase 2 - Runtime Path Audit
Deliver under `docs/cleanup/`:
- `runtime_path_truth.md`
- `state_collision_report.md`

### Phase 3 - Safe Artifact Relocation (No Runtime Code Changes)
Allowed:
- move generated artifacts/log exports/temp outputs to `artifacts/`
- move extracted text/OCR dumps to `artifacts/extracted/`

Not allowed:
- runtime behavior changes
- test behavior changes
- deletions

Deliver:
- `docs/cleanup/cleanup_changes_phase3.md`

### Phase 4 - Documentation Reorganization
- keep active docs in `docs/`
- move historical docs to `docs/archive/`
- do not delete docs in this phase

Deliver:
- `docs/cleanup/docs_index.md`
- `docs/cleanup/cleanup_changes_phase4.md`

### Phase 5 - Test Classification (No Deletion)
Deliver:
- `docs/cleanup/test_map.md`
- `docs/cleanup/test_archive_candidates.md`

### Phase 6 - Script Consolidation
- move one-off utilities into `scripts/`
- preserve deploy/CI scripts

Deliver:
- `scripts/README.md`
- `docs/cleanup/cleanup_changes_phase6.md`

### Phase 7 - Archive Pass
- move medium-confidence stale files to archive buckets
- no deletions

Deliver:
- `docs/cleanup/archive_manifest.md`

### Phase 8 - Low-Risk Deletion
Only for high-confidence dead files with proofs.

Deliver:
- `docs/cleanup/deletion_log.md`

### Phase 9 - Structural Normalization
- finalize folders and references
- keep entry points and behavior unchanged

Deliver:
- `docs/cleanup/reorg_changes_phase9.md`

### Phase 10 - Verification
Verify:
- imports resolve
- tests pass for affected areas
- runtime path resolution intact
- scheduler/state behavior unchanged

Deliver:
- `docs/cleanup/cleanup_verification.md`

## Hard Rules
Never:
- delete scheduler or strategy runtime code blindly
- delete configs without path-resolution proof
- delete tests/documents without manifest evidence
- aggressively purge `.runtime/`
- break import paths

Always:
- log every move and deletion
- keep changes reversible
- provide short rationale per action

## Decision Rules
- unsure -> `UNKNOWN_REVIEW`
- duplicate -> archive first
- clearly dead with proof -> delete candidate
- referenced -> keep

## Final Principle
Classify first. Archive second. Delete last. Prove every deletion.
