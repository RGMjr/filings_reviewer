# 07 - WS-07 Test Reliability, Infrastructure, and CI Gate Closure

## Why This Workstream Exists
Production hardening requires deterministic test infrastructure and explicit coverage for auth, degradation, scalability, throughput, and migration safety.

## Primary Touchpoints
1. `tests/conftest.py`
2. `tests/integration/web/`
3. `tests/integration/extraction_v2/`
4. `tests/performance/`
5. CI configuration files and test commands
6. `docs/PERFORMANCE_BASELINE.md`

## Scope
1. Ensure test DB setup uses forward migration contract from WS-01.
2. Add/complete auth integration coverage for production-like browser flows.
3. Add audit degradation/fault-injection tests.
4. Add scalability tests for paginated review + next-item logic.
5. Add throughput smoke tests for batch orchestration and persistence.
6. Introduce CI tiering for fast/blocking/nightly suites.

## Out of Scope
1. Perfect production traffic emulation.
2. Internet-scale load-test platform.

## Conflict Resolution from Prior Plans
1. Supersedes raw `sql/*.sql` fixture migration strategy with forward migration contract.
2. Converts isolated test fixes into permanent CI gate definitions.

## Technical Design
1. Test DB fixture invokes migration runner APIs and supports efficient reset model.
2. Fault-injection harness for DB unavailable/slow cases.
3. Deterministic large-fixture datasets for pagination and throughput checks.
4. CI tiers:
5. Tier 1: fast unit/static checks (blocking).
6. Tier 2: integration reliability checks (blocking after stabilization).
7. Tier 3: heavy performance and gold-standard checks (scheduled/nightly).

## Implementation Plan
1. Fix initialization so V2 schemas always exist under test.
2. Add auth, degradation, and scalability tests tied to workstream acceptance criteria.
3. Add throughput smoke suite for batch runner + persistence path.
4. Update CI pipeline and failure messaging.
5. Update performance baseline docs with microbenchmark vs end-to-end labels.

## Test and Validation
1. Targeted run: `tests/integration/extraction_v2/test_e2e_pipeline.py`.
2. Reliability suite: auth, degraded DB, queue overflow, pagination regression tests.
3. Scheduled suite: throughput and gold-standard quality runs.
4. Flake analysis for new tests; stabilize before promoting to blocking.

## Acceptance Criteria
1. Test DB init no longer produces missing-table errors for V2 integration tests.
2. Critical auth/degradation/scalability scenarios are covered and green.
3. CI tiers are defined, documented, and enforceable.
4. New tests are actionable and non-flaky at blocking tier.

## Rollout and Rollback
1. Merge with heavy suites non-blocking initially if needed.
2. Promote stable reliability checks to blocking.
3. Keep long-running performance/quality checks scheduled.

## Deliverables
1. Deterministic test infra and reliability suites.
2. Updated CI gate definitions.
3. Updated performance baseline documentation.
