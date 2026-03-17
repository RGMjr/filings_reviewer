"""
E2E Tests for UXI-2: Metric Dropdown Search

These tests verify the metric search functionality in the reclassify dropdown
using Playwright MCP browser automation tools.

Prerequisites:
- Flask dev server running on localhost:5003
- At least one pending review candidate in database
- Playwright MCP server configured in Claude Code

Execution:
Run these tests interactively via Claude Code using Playwright MCP tools.
Each test function documents the steps to execute and verify.

Test Coverage:
- Search Filtering: 3 tests
- Focus/State Management: 2 tests
- Keyboard Integration: 1 test
- Optional: 2 additional tests

Total: 6+ tests covering critical UXI-2 scenarios
"""

from tests.e2e.conftest import SELECTORS

# =============================================================================
# Test 1: Search Filters Metrics
# =============================================================================

def test_search_filters_metrics():
    """
    Test: Typing in search input filters the metric list.

    Steps (execute via Playwright MCP):
    1. browser_navigate to http://localhost:5003/filings
    2. browser_snapshot to see filing list
    3. browser_click on a filing row to open review page
    4. browser_snapshot to confirm on review page with pending candidate
    5. browser_press_key 'c' to open reclassify dropdown
    6. browser_snapshot to see dropdown open with search input
    7. browser_type 'arr' in the search input (ref from snapshot)
    8. browser_snapshot to verify filtering

    Expected Results:
    - Only metrics containing 'arr' should be visible (e.g., ARR, NRR)
    - Other metrics like 'Customers' should be hidden (have d-none class)
    - The visible count should be less than total metrics

    Assertions:
    - Search input should contain 'arr'
    - Visible .metric-option elements should all contain 'arr' in text
    - At least one metric should be visible
    - Not all metrics should be visible (filtering worked)

    DOM Selectors:
    - Search input: {search_input}
    - Metric options: {metric_option}
    - Visible metrics: {visible_metric}
    """.format(**SELECTORS)
    pass


# =============================================================================
# Test 2: Clear Button Resets Filter
# =============================================================================

def test_clear_button_resets_filter():
    """
    Test: Clicking the clear button (x) resets the search filter.

    Steps (execute via Playwright MCP):
    1. From test_search_filters_metrics end state (with 'arr' filter active)
       OR start fresh:
       - browser_navigate to review page
       - browser_press_key 'c' to open dropdown
       - browser_type 'arr' in search input
    2. browser_snapshot to see filtered state
    3. browser_click on clear button (.metric-search-clear)
    4. browser_snapshot to verify reset state

    Expected Results:
    - Search input should be empty
    - All metrics should be visible again
    - Search input should remain focused

    Assertions:
    - Search input value should be ''
    - All .metric-list > li elements should NOT have d-none class
    - Clear button should be hidden (not visible class)

    DOM Selectors:
    - Clear button: {clear_button}
    - Search input: {search_input}
    - Metric items: {metric_item}
    """.format(**SELECTORS)
    pass


# =============================================================================
# Test 3: No Matches Message
# =============================================================================

def test_no_matches_message():
    """
    Test: Typing a non-matching search term shows "No matching metrics".

    Steps (execute via Playwright MCP):
    1. browser_navigate to review page with pending candidate
    2. browser_press_key 'c' to open reclassify dropdown
    3. browser_snapshot to see dropdown
    4. browser_type 'xyz123' in search input (gibberish that won't match)
    5. browser_snapshot to verify no matches state

    Expected Results:
    - "No matching metrics" message should be visible
    - All metric items should be hidden (d-none class)
    - Search input should contain 'xyz123'

    Assertions:
    - .no-matches-message should have 'visible' class
    - No .metric-option should be visible
    - Search input value should be 'xyz123'

    DOM Selectors:
    - No matches message: {no_matches}
    - Search input: {search_input}
    - Visible metrics: {visible_metric}
    """.format(**SELECTORS)
    pass


# =============================================================================
# Test 4: Auto-Focus on Dropdown Open
# =============================================================================

def test_autofocus_on_open():
    """
    Test: Search input is automatically focused when dropdown opens.

    Steps (execute via Playwright MCP):
    1. browser_navigate to review page with pending candidate
    2. browser_snapshot to confirm on review page
    3. browser_press_key 'c' to open reclassify dropdown
    4. browser_snapshot to see dropdown state

    Expected Results:
    - Reclassify dropdown should be open
    - Search input should be focused (ready for typing)
    - No metric should be pre-highlighted

    Assertions:
    - Dropdown menu (.metric-selector) should be visible
    - Search input (#metric-search-input) should be the active/focused element
    - Can immediately type without clicking

    Verification:
    After browser_press_key 'c', immediately browser_type some text.
    If text appears in search input, auto-focus worked.

    DOM Selectors:
    - Dropdown menu: {dropdown_menu}
    - Search input: {search_input}
    """.format(**SELECTORS)
    pass


# =============================================================================
# Test 5: State Reset on Dropdown Close/Reopen
# =============================================================================

def test_state_reset_on_close():
    """
    Test: Closing and reopening dropdown clears search state.

    Steps (execute via Playwright MCP):
    1. browser_navigate to review page with pending candidate
    2. browser_press_key 'c' to open dropdown
    3. browser_type 'arr' to filter
    4. browser_snapshot to see filtered state
    5. browser_press_key 'Escape' to close dropdown
    6. browser_snapshot to confirm dropdown closed
    7. browser_press_key 'c' to reopen dropdown
    8. browser_snapshot to verify reset state

    Expected Results:
    - After reopening, search input should be empty
    - All metrics should be visible again
    - Search input should be focused

    Assertions:
    - Search input value should be ''
    - All metric items visible (no d-none class)
    - No matches message should NOT be visible

    DOM Selectors:
    - Search input: {search_input}
    - Metric items: {metric_item}
    - No matches: {no_matches}
    """.format(**SELECTORS)
    pass


# =============================================================================
# Test 6: Arrow Navigation on Filtered Results
# =============================================================================

def test_arrow_navigation():
    """
    Test: Arrow Down key navigates to first visible metric from search input.

    Steps (execute via Playwright MCP):
    1. browser_navigate to review page with pending candidate
    2. browser_press_key 'c' to open dropdown
    3. browser_type 'arr' to filter (should show ARR-related metrics)
    4. browser_snapshot to see filtered results
    5. browser_press_key 'ArrowDown' to move focus
    6. browser_snapshot to see focus moved to first visible item

    Expected Results:
    - First visible metric option should be highlighted/focused
    - The .keyboard-focus class should be on the first visible item
    - OR the first visible .metric-option should be document.activeElement

    Assertions:
    - A .metric-option should have focus or keyboard-focus class
    - The focused option should contain 'arr' (part of filtered set)

    DOM Selectors:
    - Visible metrics: {visible_metric}
    - Metric options: {metric_option}
    """.format(**SELECTORS)
    pass


# =============================================================================
# Test 7: Single Match Enter Select with Submission Verification
# =============================================================================

def test_single_match_enter_select():
    """
    Test: When only one metric matches, pressing Enter selects AND submits it.

    This test verifies the FULL reclassification flow from search to submission.

    Steps (execute via Playwright MCP):
    1. browser_navigate to review page with pending candidate
    2. browser_snapshot to record current URL and candidate ID
    3. browser_press_key 'c' to open dropdown
    4. browser_type a unique search term that matches only one metric
       (e.g., 'dau' for Daily Active Users, or 'logo' for Logo Retention)
    5. browser_snapshot to verify single match visible
    6. browser_press_key 'Enter' to select and submit
    7. browser_wait_for text='Success' (toast notification)
    8. browser_snapshot to verify navigation occurred

    Expected Results:
    - Dropdown should close after Enter
    - Success toast notification should appear (contains "Success")
    - Page should navigate to next candidate OR filings list
    - URL should change from original (proves navigation happened)

    Assertions:
    - Toast with "Success" text visible within 2 seconds
    - URL changed from original review page
    - If next candidate exists: new candidate ID in URL
    - If no more candidates: redirects to /filings

    Note: This test requires knowing which search terms produce single matches.
    Check the metric dropdown content first via browser_snapshot.
    Good single-match terms: 'dau', 'mau', 'wau', 'logo', 'gmv'

    DOM Selectors:
    - Search input: {search_input}
    - Visible metrics: {visible_metric}
    - Success toast: .alert-success, .toast-success, or text "Success"
    """.format(**SELECTORS)
    pass


# =============================================================================
# Test 8 (Optional): Case Insensitivity
# =============================================================================

def test_case_insensitivity():
    """
    Test: Search is case-insensitive ('ARR' and 'arr' show same results).

    Steps (execute via Playwright MCP):
    1. browser_navigate to review page with pending candidate
    2. browser_press_key 'c' to open dropdown
    3. browser_type 'ARR' (uppercase)
    4. browser_snapshot - count visible metrics
    5. Clear search (click clear button or press Escape, reopen)
    6. browser_type 'arr' (lowercase)
    7. browser_snapshot - count visible metrics

    Expected Results:
    - Both searches should show the same metrics
    - Visible count should be identical

    Assertions:
    - Number of visible metrics with 'ARR' == number with 'arr'
    - Same metric IDs should be visible in both cases

    DOM Selectors:
    - Search input: {search_input}
    - Visible metrics: {visible_metric}
    - Clear button: {clear_button}
    """.format(**SELECTORS)
    pass


# =============================================================================
# Helper: Get First Review Candidate URL
# =============================================================================

def get_test_setup_instructions():
    """
    Instructions for setting up test data and navigation.

    To find a review page with pending candidates:

    1. Navigate to filings list:
       browser_navigate('http://localhost:5003/filings')

    2. Take snapshot to see filings:
       browser_snapshot()

    3. Look for a filing with pending candidates (Pending column > 0)

    4. Click on the filing row or its review link

    5. Take snapshot to confirm on review page with Reclassify button visible

    If no filings have pending candidates:
    - Run: DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \\
           python scripts/generate_review_candidates.py

    Alternative: Use database to find a candidate directly:
    SELECT rc.candidate_id, f.filing_id
    FROM review_candidates rc
    JOIN filings f ON rc.filing_id = f.filing_id
    WHERE rc.review_status = 'pending'
    LIMIT 1;

    Then navigate to: http://localhost:5003/review/{filing_id}?candidate_id={candidate_id}
    """
    pass


# =============================================================================
# Test Summary
# =============================================================================
"""
TEST SUMMARY - UXI-2 Metric Dropdown Search E2E Tests
=====================================================

Required Tests (7):
1. test_search_filters_metrics - Type "arr", verify filtering
2. test_clear_button_resets_filter - Click X, verify all visible
3. test_no_matches_message - Type "xyz123", verify message
4. test_autofocus_on_open - Press C, verify input focused
5. test_state_reset_on_close - Close/reopen, verify cleared
6. test_arrow_navigation - Type + ArrowDown, verify focus
7. test_single_match_enter_select - Single match + Enter + verify submission

Optional Tests (1):
8. test_case_insensitivity - ARR vs arr comparison

Execution Order:
For efficiency, run tests in sequence reusing browser state where possible:
1. Navigate to review page
2. Test 4 (autofocus) - just opened dropdown
3. Test 1 (filter) - type 'arr'
4. Test 6 (arrow nav) - continue from filtered state
5. Test 2 (clear) - clear and verify
6. Test 3 (no matches) - type 'xyz123'
7. Test 5 (close/reopen) - escape and reopen
8. Test 7 (submission) - single match + Enter, verify toast + navigation

Pass Criteria:
- All 7 required tests must pass
- UI should respond within 1 second for each interaction
- No console errors during tests
- Test 7 must verify success toast AND navigation occurs
"""
