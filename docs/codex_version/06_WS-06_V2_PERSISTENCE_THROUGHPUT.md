# 06 - WS-06 V2 Persistence Throughput Optimization

## Why This Workstream Exists
Row-by-row persistence is a bottleneck for high-volume ingestion and undermines batch-run throughput goals.

## Primary Touchpoints
1. `src/extraction_v2/persistence.py`
2. `src/infra/db.py` (if helper APIs are required)
3. `tests/integration/extraction_v2/test_persistence.py`
4. `tests/performance/`

## Scope
1. Replace per-row persistence loops with chunked bulk operations.
2. Preserve current idempotency/conflict semantics.
3. Keep transactional consistency for `persist_pipeline_result`.
4. Add persistence-focused benchmark coverage.

## Out of Scope
1. Schema redesign not required for throughput gains.
2. Partitioning/sharding architecture changes.

## Technical Design
1. Use chunked bulk writes (`executemany` or equivalent multi-row strategy).
2. Keep per-filing transaction boundary.
3. Preserve ON CONFLICT keys and update semantics.
4. Make chunk sizes configurable for tuning.

## Implementation Plan
1. Baseline persistence throughput with representative fixtures.
2. Implement bulk writes for each persisted entity type.
3. Add chunking utility with uniform error handling.
4. Verify persisted outcomes match pre-change baseline.
5. Add benchmark test and documentation.

## Test and Validation
1. Integration: compare row counts and representative value fields before/after.
2. Idempotency: rerun same filing; assert no duplicate logical facts.
3. Performance: benchmark delta documented and reproducible.

## Acceptance Criteria
1. Functional outputs are equivalent to baseline.
2. Throughput improves materially on large fixtures.
3. Conflict and idempotency behavior remains correct.
4. Integration tests remain green.

## Rollout and Rollback
1. Optionally gate bulk mode with feature flag.
2. Enable in staging first; monitor lock times and transaction durations.
3. Rollback by disabling bulk mode if contention/regression is observed.

## Deliverables
1. Bulk persistence implementation.
2. Benchmarks and before/after report.
3. Updated tests for persistence behavior.
