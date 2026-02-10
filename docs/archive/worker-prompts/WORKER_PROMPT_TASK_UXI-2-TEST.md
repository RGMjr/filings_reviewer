# WORKER PROMPT: Task UXI-2-TEST - Playwright E2E Tests for Metric Dropdown Search

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       UXI-2-TEST
TASK NAME:     Create Playwright E2E tests for UXI-2 metric dropdown search
WORKSTREAM:    UX Improvements (Testing)
SOURCE:        docs/UX_IMPROVEMENT_PLAN.md, docs/WORKER_PROMPT_TASK_UXI-2.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3h (breakdown: infrastructure 45 min, tests 90 min, documentation 15 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low (additive tests, no production code changes)
TASK SIZE:     M
DEPENDS ON:    UXI-2 (must be implemented first)
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create automated browser tests using Playwright MCP to verify UXI-2 (metric dropdown search) works correctly.

**Business Rationale**: Manual browser testing is time-consuming and error-prone. Automated E2E tests catch regressions when future changes are made to the review interface.

**Current Behavior**: No E2E tests exist. UXI-2 testing is purely manual (12 test scenarios documented in worker prompt).

**Desired Behavior**: Automated Playwright tests that verify critical UXI-2 functionality can be run via Claude Code MCP integration.

## Prerequisites

- UXI-2 must be fully implemented (search input, filtering, keyboard integration)
- Flask dev server must be running with test data
- Playwright MCP server available (`claude mcp add playwright`)

## Files to Create

1. **`tests/e2e/__init__.py`** - Package marker
2. **`tests/e2e/conftest.py`** - Shared E2E fixtures and utilities
3. **`tests/e2e/test_metric_dropdown_search.py`** - UXI-2 E2E tests

## Files to Read (Context Only)

- `docs/WORKER_PROMPT_TASK_UXI-2.md` - Test scenarios and acceptance criteria
- `src/web/templates/review.html` - DOM structure for selectors
- `src/web/static/js/review.js` - JavaScript behavior to verify

## Implementation Requirements

### Core Functionality

1. **Test Infrastructure Setup**
   - Create `tests/e2e/` directory structure
   - Document how to run tests with Playwright MCP
   - Include instructions for test data setup

2. **E2E Test Coverage**

   Automate these critical scenarios from UXI-2 (6 tests minimum):

   | # | Scenario | Verification |
   |---|----------|--------------|
   | 1 | Press C, type "arr" | Only ARR metric visible |
   | 2 | Click × button | All metrics visible |
   | 3 | Type "xyz123" | "No matching metrics" shown |
   | 4 | Open dropdown | Search input is focused |
   | 5 | Type, Arrow Down | First visible item highlighted |
   | 6 | Close/reopen dropdown | Search cleared, all visible |

   Optional (if time permits):
   | 7 | Filter to 1 result, Enter | Metric selected without arrow |
   | 8 | Case insensitivity | "ARR" and "arr" same results |

3. **Test Utilities**
   - Helper to navigate to review page with test candidate
   - Helper to open reclassify dropdown (via keyboard or click)
   - Helper to count visible metric options
   - Helper to get search input state (value, focused)

### Test Data Requirements

- Tests require at least one review candidate in the database
- Document the required database state in conftest.py comments
- Provide setup commands for test data

### Error Handling

- **No test candidate**: Skip test with clear message
- **Server not running**: Skip test with setup instructions
- **Timeout**: Use reasonable timeouts (5s for page load, 1s for UI updates)

## Test Requirements

### Coverage Target: **6+ E2E tests** for UXI-2 functionality

### Test Categories

1. **Search Filtering** (3 tests)
   - Filter shows matching metrics
   - Filter hides non-matching metrics
   - "No matches" message appears when appropriate

2. **Focus/State Management** (2 tests)
   - Auto-focus on dropdown open
   - State reset on dropdown close

3. **Keyboard Integration** (1 test)
   - Arrow navigation works on filtered results

## Acceptance Criteria

- [ ] `tests/e2e/` directory exists with package marker
- [ ] `conftest.py` documents test prerequisites and data setup
- [ ] 6+ E2E tests covering critical UXI-2 scenarios
- [ ] Tests use Playwright MCP browser tools
- [ ] All tests pass when run against working UXI-2 implementation
- [ ] README or docstrings explain how to run tests
- [ ] Tests handle missing test data gracefully (skip, not fail)

## Do NOT

- Modify any production code (this is test-only)
- Install Playwright as a Python dependency (use MCP)
- Create tests that require specific candidate IDs (use dynamic lookup)
- Write tests for features other than UXI-2

## Verification Commands

```bash
# Ensure Flask server is running with test data
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 -m flask --app src.web.app run --debug &

# Run E2E tests via Claude Code with Playwright MCP
# (Tests are executed interactively through Claude Code)

# Verify test files exist
ls -la tests/e2e/
```

## Example Test Structure

**Note**: This is for reference only - adapt to Playwright MCP patterns.

```python
# tests/e2e/test_metric_dropdown_search.py

"""
E2E tests for UXI-2: Metric Dropdown Search

Prerequisites:
- Flask dev server running on localhost:5000
- At least one review candidate in database
- Playwright MCP server configured

Run via Claude Code:
1. Ensure server is running
2. Use browser_navigate, browser_click, browser_type, browser_snapshot tools
"""

# Test 1: Search filtering reduces visible metrics
async def test_search_filters_metrics():
    """
    Steps:
    1. Navigate to /review/candidate/<id>
    2. Press 'C' to open reclassify dropdown
    3. Type 'arr' in search input
    4. Verify only metrics containing 'arr' are visible
    """
    pass

# Test 2: Clear button resets filter
async def test_clear_button_resets_filter():
    """
    Steps:
    1. Navigate and open dropdown
    2. Type search term
    3. Click × clear button
    4. Verify all metrics visible again
    """
    pass
```

## Critical Evaluation Phase

**Required for all tasks. Depth: Standard (M task)**

After verification passes but BEFORE committing:
1. Code Quality Review - Test naming, assertions, documentation
2. Test Coverage Assessment - All 6 critical scenarios covered
3. Architecture Alignment - Uses MCP tools correctly, follows project patterns
4. Identify Improvements - Additional scenarios, better selectors, parallel execution
5. **User Approval (REQUIRED)** - STOP and ask before proceeding
6. Implement Approved Changes
7. Generate Follow-Up Tasks for additional E2E test coverage
8. Commit and Push

## Reference

- **Issue source**: UX Improvement Plan - UXI-2 Testing
- **Dependencies**: UXI-2 (implementation), Playwright MCP
- **Related**: UXI-2 worker prompt test scenarios

---

**Last Updated**: 2026-01-07
**Format Version**: 2.6
