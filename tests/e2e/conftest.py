"""
E2E Test Configuration and Utilities

This module provides documentation and utilities for E2E tests using Playwright MCP.

IMPORTANT: These tests are NOT run via pytest. They are executed interactively
through Claude Code using Playwright MCP browser tools.

Prerequisites:
--------------
1. Flask dev server running:
   DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \\
     python3 -m flask --app src.web.app run --debug --port 5003

2. At least one pending review candidate in the database.
   To check: SELECT COUNT(*) FROM review_candidates WHERE review_status = 'pending';

3. Playwright MCP server configured:
   claude mcp add --transport stdio playwright -- npx -y @playwright/mcp@latest

Test Data Setup:
----------------
If no review candidates exist, generate them:
   DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \\
     python scripts/generate_review_candidates.py

Key Selectors (UXI-2 Metric Dropdown Search):
---------------------------------------------
- Reclassify button: .btn-warning.dropdown-toggle
- Search input: #metric-search-input
- Clear button: .metric-search-clear
- Metric options: .metric-list > li > .metric-option
- No matches message: .no-matches-message
- Dropdown menu: .metric-selector

Keyboard Shortcuts:
-------------------
- 'C' key: Opens reclassify dropdown (when not in input field)
- Arrow Down: Navigate to first visible metric from search
- Enter: Select highlighted/single-match metric
- Escape: Close dropdown

How to Run Tests:
-----------------
1. Ensure Flask server is running on port 5003
2. In Claude Code, execute tests using Playwright MCP tools:
   - browser_navigate: Navigate to review pages
   - browser_snapshot: Capture page state
   - browser_click: Click elements
   - browser_type: Type in inputs
   - browser_press_key: Press keyboard keys
   - browser_wait_for: Wait for text/elements

Example test execution sequence:
   1. browser_navigate to http://localhost:5003/filings
   2. browser_snapshot to see available filings
   3. browser_click on a filing with pending candidates
   4. browser_snapshot to see review page
   5. browser_press_key 'c' to open reclassify dropdown
   6. browser_type to enter search text
   7. browser_snapshot to verify filtering

Test Categories:
----------------
1. Search Filtering (3 tests)
   - test_search_filters_metrics: Type "arr" shows only ARR-related metrics
   - test_search_hides_nonmatching: Non-matching metrics are hidden
   - test_no_matches_message: "xyz123" shows "No matching metrics"

2. Focus/State Management (2 tests)
   - test_autofocus_on_open: Search input focused when dropdown opens
   - test_state_reset_on_close: Closing/reopening clears search

3. Keyboard Integration (1 test)
   - test_arrow_navigation: ArrowDown moves focus to filtered results
"""

# DOM Selectors for UXI-2 tests
SELECTORS = {
    # Reclassify dropdown
    "reclassify_button": ".btn-warning.dropdown-toggle",
    "dropdown_menu": ".metric-selector",

    # Search components (UXI-2)
    "search_input": "#metric-search-input",
    "clear_button": ".metric-search-clear",
    "metric_list": ".metric-list",
    "metric_option": ".metric-option",
    "metric_item": ".metric-list > li",
    "visible_metric": ".metric-list > li:not(.d-none)",
    "no_matches": ".no-matches-message",

    # Feedback/notifications
    "success_toast": ".alert-success",
    "error_toast": ".alert-danger",

    # Navigation
    "filings_link": "a[href='/filings']",
    "filing_row": ".filing-row",
    "candidate_link": ".list-group-item[data-candidate-id]",
}

# Test URLs
BASE_URL = "http://localhost:5003"
FILINGS_URL = f"{BASE_URL}/filings"


def get_review_url(filing_id: int, candidate_id: int | None = None) -> str:
    """Generate review page URL for a filing."""
    url = f"{BASE_URL}/review/{filing_id}"
    if candidate_id:
        url += f"?candidate_id={candidate_id}"
    return url


# Expected metric count (approximate, based on metric_keywords.yaml)
EXPECTED_METRIC_COUNT_MIN = 15  # Minimum expected metrics in dropdown
