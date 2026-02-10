# WORKER PROMPT: Task UXI-2-TEST-F1 - E2E Test for Reclassify Selection Submission

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       UXI-2-TEST-F1
TASK NAME:     Add E2E test verifying Enter key submits reclassification decision
WORKSTREAM:    Testing Improvements
SOURCE:        UXI-2-TEST completion evaluation - improvement suggestion #1
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1-2 hours (test design 30 min, implementation 45 min, verification 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    None (additive tests only)
TASK SIZE:     S
DEPENDS ON:    UXI-2-TEST (must be complete)
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: UXI-2-TEST-F2, UXI-2-TEST-F3, UXI-2-TEST-F4
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add an E2E test that verifies pressing Enter on a single-match search actually submits a reclassification decision and updates the candidate status.

**Business Rationale**: The current E2E tests verify the search UI works, but don't confirm the full workflow completes successfully. This test ensures the Enter-to-select feature actually triggers the API submission.

**Current Behavior**: Test coverage stops at verifying focus moves to the metric option. No test confirms the decision is actually submitted.

**Desired Behavior**: E2E test verifies that pressing Enter on single match submits reclassification via API and navigates to next candidate.

## Prerequisites

- UXI-2-TEST complete (tests/e2e/ directory exists)
- Flask dev server running with test database
- At least one pending review candidate

## Files to Modify

1. **`tests/e2e/test_metric_dropdown_search.py`** - Add test_reclassify_submission_flow test

## Files to Read (Context Only)

- `tests/e2e/conftest.py` - Existing selectors and utilities
- `src/web/static/js/review.js` - Understand submission flow (line 899-962)
- `src/web/routes/api.py` - Understand API response format

## Implementation Requirements

### Core Functionality

1. **Test Flow**
   - Navigate to review page with pending candidate
   - Record current candidate ID
   - Open reclassify dropdown with 'C' key
   - Type unique search term (e.g., "gmv" for single match)
   - Press Enter to select and submit
   - Verify success flash message appears
   - Verify URL changes (navigation to next candidate)

2. **Assertions**
   - Decision API returns success
   - Success toast notification appears
   - Page navigates away from original candidate
   - OR if last candidate, navigates to filings list

### Error Handling

- **Network Error**: Test should timeout gracefully if server not responding
- **No Candidates**: Skip test with clear message if no pending candidates

## Test Requirements

### Coverage Target: N/A (E2E test, not unit coverage)

### Test Categories (1 test)

1. **Full Submission Flow** (1 test)
   - `test_reclassify_submission_flow` - Complete workflow from search to navigation

### Known Edge Cases to Test

- Single match scenario (Enter auto-selects)
- Verify toast message text includes "Success"

## Acceptance Criteria

- [ ] New test `test_reclassify_submission_flow` added
- [ ] Test documents all Playwright MCP steps clearly
- [ ] Test can be executed via Playwright MCP tools
- [ ] Test verifies success toast appears
- [ ] Test verifies navigation occurs

## Do NOT

- Modify production code (src/)
- Change existing tests
- Add external dependencies

## Verification Commands

```bash
# Verify test file syntax
python3 -c "import tests.e2e.test_metric_dropdown_search"

# Execute test manually via Playwright MCP following documented steps
```

---

**Last Updated**: 2026-01-07
**Format Version**: 2.6
