# 04 - WS-04 Review Route and API Query Scalability

## Why This Workstream Exists
Unbounded full-list loading and Python-side navigation logic do not scale for large filings and concurrent reviewers.

## Primary Touchpoints
1. `src/web/routes/review.py`
2. `src/web/routes/review_v2.py`
3. `src/web/routes/api.py`
4. `src/web/routes/api_v2.py`
5. `src/infra/db.py`
6. `sql/07_create_review_schema.sql`
7. `sql/09_v2_schema.sql`

## Scope
1. Replace default full-list loading with paginated/targeted queries.
2. Move next-item selection logic into SQL.
3. Add/tune indexes for actual WHERE/ORDER patterns.
4. Preserve existing user-visible behavior and API contracts.

## Out of Scope
1. UI redesign.
2. New product search features.

## Technical Design
1. Add DB methods for paginated retrieval, status counts, and next-item lookup.
2. Route handlers request only visible data plus separate aggregates.
3. Add explain-plan snapshots for critical query paths.
4. Preserve route contract compatibility.

## Implementation Plan
1. Document current filter/sort contract.
2. Implement repository/query methods.
3. Update route handlers and any required pagination metadata.
4. Apply index migrations where justified by explain plans.
5. Add regression and performance tests on large synthetic fixtures.

## Test and Validation
1. Correctness: old vs new behavior parity on representative fixtures.
2. Scalability: large filing datasets with concurrent reviewer simulation.
3. Performance: endpoint p95/p99 tracking before/after.

## Acceptance Criteria
1. No default route/API path loads full candidate/fact set.
2. Next-item lookup complexity is bounded and DB-driven.
3. Counts/filters remain accurate.
4. Endpoint latency scaling improves materially with filing size growth.

## Rollout and Rollback
1. Route-level feature flag if needed.
2. Stage with parity checks.
3. Production enable with endpoint latency and DB load monitoring.

## Deliverables
1. Scalable query methods and route wiring.
2. Supporting index changes.
3. Performance and regression evidence.
