# Analysis Plan: End-to-End Testing Audit

**Created**: 2026-02-05
**Purpose**: Comprehensive audit of E2E testing infrastructure for V2 merge readiness
**Mode**: Ralph analyze (isolated branch)
**Branch**: `ralph/analyze-e2e-testing-20260205`

---

## Problem Statement

The V2 extraction pipeline is approaching merge readiness. We need to audit the current E2E testing infrastructure against the documented strategy (`docs/V2_E2E_TESTING_STRATEGY.md`) to identify gaps, assess coverage, and verify that pre-merge blockers are addressed.

---

## Tasks

### TASK-1: Audit Pipeline E2E Coverage
- [x] Compare `tests/integration/extraction_v2/test_e2e_pipeline.py` against the 11-stage pipeline
- [x] Verify each stage has explicit test assertions
- [x] Check gold standard filing coverage (Slack, Samsara, Shopify, Datadog)
- [x] Identify missing stages or weak assertions

### TASK-2: Assess Persistence E2E Tests
- [x] Review `TestE2EPersistence` for complete roundtrip coverage
- [x] Verify all V2 tables are tested: v2_documents, v2_segments, v2_metric_facts, v2_tables, v2_image_assets
- [x] Check evidence_pack retrieval tests exist
- [x] Identify any schema columns not covered by tests

### TASK-3: Evaluate V1/V2 Comparison Tests
- [x] Check if formal V1/V2 comparison tests exist (per strategy doc)
- [x] Verify the "≥95% of V1 metrics" criterion is testable
- [x] Review `scripts/benchmark_v1_v2.py` for integration into test suite
- [x] Document gap if no automated comparison exists

### TASK-4: Review API Endpoint E2E Status
- [x] Check `tests/integration/web/` for V2-specific API tests
- [x] Review routes in `src/web/routes/` for V2 endpoints
- [x] Identify which V2 API endpoints lack E2E tests
- [x] Assess priority based on user-facing impact

### TASK-5: Audit Browser E2E Tests
- [x] Review `tests/e2e/test_metric_dropdown_search.py` completeness
- [x] Check if tests are runnable with current Playwright setup
- [x] Identify UI features that lack browser E2E coverage
- [x] Document infrastructure requirements (Flask server, database)

### TASK-6: Verify Pre-Merge Success Criteria
- [x] Cross-reference strategy's "Success Criteria for Merge" against actual tests
- [x] Create a checklist of criteria with pass/fail status
- [x] Identify blocking gaps that must be addressed before merge

### TASK-7: Edge Case Coverage Analysis
- [x] Review test fixtures for edge cases (empty filing, malformed tables, etc.)
- [x] Check if synthetic test fixtures from strategy exist
- [x] Identify missing edge case scenarios
- [x] Document impact on merge readiness

### TASK-8: Idempotency and Performance Tests
- [x] Review `TestE2EIdempotency` implementation
- [x] Check `TestE2EPerformance` against 30-second gate
- [x] Verify performance regression detection mechanism
- [x] Document any timing variability concerns

---

## Analysis Output

Results will be written to: `ops/ANALYSIS_RESULTS.md`

Final deliverable: Gap analysis report with:
1. Coverage matrix (what's tested vs. not tested)
2. Pre-merge blockers identified
3. Recommendations prioritized by merge impact
4. Specific action items for each gap

---

## Statistics

| Metric | Count |
|--------|-------|
| Tasks Defined | 8 |
| Tasks Complete | 8 |
| Files Analyzed | 12 |
| Gaps Identified | 8 |
| Pre-Merge Blockers | 1-2 |
