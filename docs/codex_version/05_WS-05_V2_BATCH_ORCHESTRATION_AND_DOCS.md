# 05 - WS-05 V2 Batch Orchestration and Production Docs Unification

## Why This Workstream Exists
Production operation for thousands of filings requires one canonical V2 execution path with resumability, explicit failure recovery, and clear docs.

## Primary Touchpoints
1. `scripts/run_v2_extraction.py`
2. `scripts/run_extraction_pipeline.py`
3. `scripts/run_v2_batch_extraction.py` (new)
4. `src/infra/sec_client.py`
5. `README.md`
6. `docs/README.md`
7. `docs/operations/setup-guide.md`
8. `docs/operations/deployment-guide.md`

## Scope
1. Create canonical batch runner for V2 production runs.
2. Add resumable state machine (`pending`, `in_progress`, `done`, `failed`).
3. Add explicit retry, interruption recovery, and run summaries.
4. Unify docs so production guidance points to one V2 path.
5. Resolve high-value TODOs that directly impact V2 production readiness.

## Out of Scope
1. Net-new V1 production capabilities.
2. Full external orchestration platform migration.

## Conflict Resolution from Prior Plans
1. Canonical runner name is `scripts/run_v2_batch_extraction.py` (single source of truth).
2. Sequential safety concern is preserved via default `--workers 1`.
3. Concurrency is supported with guarded flag (`--workers >1`) after staging validation.
4. V1 runner TODO cleanup is allowed only when needed for safe compatibility, not feature expansion.

## Technical Design
1. New CLI script options:
2. `--limit`
3. `--workers` (default `1`)
4. `--resume`
5. `--retry-failed`
6. `--filing-id` and/or filter selectors
7. `--dry-run`
8. Deterministic filing selection and leasing semantics for worker safety.
9. Structured run summary with counts, failure list, durations, and optional cost metrics.
10. `sec_client` paths fully routed through `src/infra/http_client.py` contract.

## Implementation Plan
1. Define runner state transitions and idempotency behavior.
2. Implement sequential core path first.
3. Add resumability and retry logic.
4. Add optional bounded concurrency.
5. Add per-filing exception isolation and continuation behavior.
6. Standardize docs to V2 batch runbook and mark V1 as legacy.

## Test and Validation
1. Integration: batch run of small corpus (`>=2`) with one induced failure.
2. Integration: interrupted run resumes without duplication.
3. Validation: retry-failed only reprocesses failed filings.
4. Typing/tests: strict checks for runner and touched infra modules.

## Acceptance Criteria
1. `run_v2_batch_extraction.py` is canonical and documented for production.
2. Default safe mode (`--workers 1`) works end-to-end.
3. Resume and retry behaviors are deterministic and idempotent.
4. Docs consistently direct operators to V2 batch path.
5. TODO cleanup delivered for V2-critical sec client path.

## Rollout and Rollback
1. Rollout in phases: pilot (50-100 filings), cohort, full corpus.
2. Rollback by pausing batch runner and using resume state after fix.

## Deliverables
1. New canonical V2 batch runner.
2. Unified production docs and onboarding entry points.
3. Orchestration evidence artifact.
