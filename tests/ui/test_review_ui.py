"""
Playwright tests for review UI compact layout and metric dropdown features.

Tests:
  A1. Collapsible filing header
  A2. Compact value+metric bar
  A3. Decision form merged into candidate card
  B1. Recently-used metrics in reclassify dropdown
  B2. Pre-highlight suggested metric in dropdown
"""
import subprocess
import sys
import os
import time
import signal

import pytest

# Playwright sync API
from playwright.sync_api import sync_playwright, expect

SERVER_PORT = 5199
SERVER_URL = f'http://localhost:{SERVER_PORT}'
TEST_DIR = os.path.dirname(os.path.abspath(__file__))

server_process = None


def pytest_configure(config):
    """Start the mock Flask server before tests."""
    global server_process
    server_process = subprocess.Popen(
        [sys.executable, os.path.join(TEST_DIR, 'test_server.py')],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for server to be ready
    for _ in range(30):
        time.sleep(0.2)
        try:
            import urllib.request
            urllib.request.urlopen(SERVER_URL, timeout=1)
            break
        except Exception:
            continue
    else:
        server_process.kill()
        raise RuntimeError('Mock server failed to start')


def pytest_unconfigure(config):
    """Stop the mock Flask server."""
    global server_process
    if server_process:
        server_process.send_signal(signal.SIGTERM)
        server_process.wait(timeout=5)


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    pg = context.new_page()
    yield pg
    context.close()


# =========================================================================
# A1: Collapsible Filing Header
# =========================================================================

class TestCollapsibleHeader:
    def test_header_has_collapse_toggle(self, page):
        """Filing header should have a chevron toggle button."""
        page.goto(SERVER_URL)
        toggle = page.locator('.filing-header-toggle')
        expect(toggle).to_be_visible()
        expect(toggle).to_have_attribute('data-bs-toggle', 'collapse')
        expect(toggle).to_have_attribute('data-bs-target', '#filing-header-details')

    def test_header_details_visible_by_default(self, page):
        """Metadata section should be visible on first load."""
        page.goto(SERVER_URL)
        details = page.locator('#filing-header-details')
        expect(details).to_be_visible()

    def test_header_collapse_on_toggle_click(self, page):
        """Clicking toggle should collapse the metadata section."""
        page.goto(SERVER_URL)
        toggle = page.locator('.filing-header-toggle')
        toggle.click()
        # Wait for Bootstrap collapse animation
        page.wait_for_timeout(400)
        details = page.locator('#filing-header-details')
        expect(details).not_to_be_visible()

    def test_header_expand_on_second_click(self, page):
        """Clicking toggle again should re-expand the metadata."""
        page.goto(SERVER_URL)
        toggle = page.locator('.filing-header-toggle')
        toggle.click()
        page.wait_for_timeout(400)
        toggle.click()
        page.wait_for_timeout(400)
        details = page.locator('#filing-header-details')
        expect(details).to_be_visible()

    def test_form_type_badge_visible(self, page):
        """Form type badge should always be visible in compact header."""
        page.goto(SERVER_URL)
        badge = page.locator('#filing-header-card .badge.bg-secondary')
        expect(badge).to_be_visible()
        expect(badge).to_have_text('S-1')

    def test_breadcrumb_always_visible(self, page):
        """Breadcrumb should remain visible when header is collapsed."""
        page.goto(SERVER_URL)
        toggle = page.locator('.filing-header-toggle')
        toggle.click()
        page.wait_for_timeout(400)
        breadcrumb = page.locator('#filing-header-card .breadcrumb')
        expect(breadcrumb).to_be_visible()
        expect(breadcrumb).to_contain_text('Acme Corp')


# =========================================================================
# A2: Compact Value + Metric Bar
# =========================================================================

class TestCompactValueMetricBar:
    def test_compact_bar_exists(self, page):
        """Compact bar should be present on the page."""
        page.goto(SERVER_URL)
        bar = page.locator('.compact-value-metric-bar')
        expect(bar).to_be_visible()

    def test_compact_bar_shows_value(self, page):
        """Bar should display the formatted parsed value."""
        page.goto(SERVER_URL)
        value = page.locator('.compact-bar-value')
        expect(value).to_be_visible()
        expect(value).to_contain_text('$1,234,567.89')

    def test_compact_bar_shows_metric(self, page):
        """Bar should display the suggested metric name."""
        page.goto(SERVER_URL)
        metric = page.locator('.compact-bar-metric')
        expect(metric).to_be_visible()
        expect(metric).to_contain_text('Cm Net Revenue Retention')

    def test_compact_bar_shows_confidence(self, page):
        """Bar should display the confidence badge."""
        page.goto(SERVER_URL)
        confidence = page.locator('.compact-bar-confidence')
        expect(confidence).to_be_visible()
        expect(confidence).to_contain_text('High')
        expect(confidence).to_contain_text('85%')

    def test_compact_bar_shows_details_row(self, page):
        """Second row should show raw text and keyword."""
        page.goto(SERVER_URL)
        details = page.locator('.compact-bar-details')
        expect(details).to_be_visible()
        expect(details).to_contain_text('1,234,567.89')
        expect(details).to_contain_text('revenue retention')

    def test_no_separate_value_card(self, page):
        """The old separate 'Extracted Value' card heading should not exist."""
        page.goto(SERVER_URL)
        # The old cards had h6 headings - verify they're gone
        old_value_heading = page.get_by_text('Extracted Value', exact=True)
        expect(old_value_heading).to_have_count(0)

    def test_no_separate_metric_card(self, page):
        """The old separate 'Suggested Metric' card heading should not exist."""
        page.goto(SERVER_URL)
        old_metric_heading = page.get_by_text('Suggested Metric', exact=True)
        expect(old_metric_heading).to_have_count(0)

    def test_feature_badges_in_bar(self, page):
        """Feature badges (Definition) should appear in compact bar."""
        page.goto(SERVER_URL)
        badge = page.locator('.compact-bar-badge')
        # Our mock has contains_definition_language=True
        expect(badge.first).to_be_visible()
        expect(badge.first).to_contain_text('Definition')


# =========================================================================
# A3: Decision Form Merged into Candidate Card
# =========================================================================

class TestMergedDecisionForm:
    def test_single_candidate_card(self, page):
        """There should be exactly one candidate-card, containing the form."""
        page.goto(SERVER_URL)
        cards = page.locator('.candidate-card')
        expect(cards).to_have_count(1)

    def test_decision_form_inside_candidate_card(self, page):
        """The decision form should be inside the candidate card."""
        page.goto(SERVER_URL)
        form = page.locator('.candidate-card #decision-form')
        expect(form).to_be_visible()

    def test_accept_button_visible(self, page):
        """Accept button should be visible in merged layout."""
        page.goto(SERVER_URL)
        accept = page.locator('[data-decision="accept"]')
        expect(accept).to_be_visible()

    def test_reject_dropdown_visible(self, page):
        """Reject dropdown should be visible in merged layout."""
        page.goto(SERVER_URL)
        reject = page.locator('.btn-danger.dropdown-toggle')
        expect(reject).to_be_visible()

    def test_reclassify_dropdown_visible(self, page):
        """Reclassify dropdown should be visible in merged layout."""
        page.goto(SERVER_URL)
        reclassify = page.locator('.btn-warning.dropdown-toggle')
        expect(reclassify).to_be_visible()

    def test_hr_separator_exists(self, page):
        """An hr separator should divide context from decision form."""
        page.goto(SERVER_URL)
        hr = page.locator('.candidate-card hr')
        expect(hr).to_have_count(1)

    def test_already_reviewed_shows_inline(self, page):
        """Already-reviewed page should show decision info inside candidate card."""
        page.goto(f'{SERVER_URL}/reviewed')
        alert = page.locator('.candidate-card .alert-info')
        expect(alert).to_be_visible()
        expect(alert).to_contain_text('Already Reviewed')


# =========================================================================
# B1: Recently-Used Metrics
# =========================================================================

class TestRecentMetrics:
    def test_no_recent_section_initially(self, page):
        """No recent section should appear with empty localStorage."""
        page.goto(SERVER_URL)
        # Clear any stale localStorage
        page.evaluate('localStorage.removeItem("recentMetrics")')
        # Open reclassify dropdown
        page.locator('.btn-warning.dropdown-toggle').click()
        page.wait_for_timeout(200)
        recent = page.locator('.recent-metrics-section')
        expect(recent).to_have_count(0)

    def test_recent_section_appears_with_data(self, page):
        """Recent section should appear when localStorage has recent metrics."""
        page.goto(SERVER_URL)
        # Seed localStorage with recent metrics
        page.evaluate('''
            localStorage.setItem("recentMetrics",
                JSON.stringify(["cm_arpu", "cm_churn_rate"]))
        ''')
        # Open reclassify dropdown
        page.locator('.btn-warning.dropdown-toggle').click()
        page.wait_for_timeout(200)
        recent = page.locator('.recent-metrics-section')
        expect(recent).to_be_visible()
        expect(recent).to_contain_text('Recent')
        expect(recent).to_contain_text('Average Revenue Per User')
        expect(recent).to_contain_text('Churn Rate')

    def test_recent_section_limited_to_valid_metrics(self, page):
        """Recent section should skip metric IDs not in the dropdown."""
        page.goto(SERVER_URL)
        page.evaluate('''
            localStorage.setItem("recentMetrics",
                JSON.stringify(["cm_nonexistent", "cm_arpu"]))
        ''')
        page.locator('.btn-warning.dropdown-toggle').click()
        page.wait_for_timeout(200)
        recent = page.locator('.recent-metrics-section')
        expect(recent).to_be_visible()
        # Only cm_arpu should appear
        recent_items = recent.locator('.metric-option')
        expect(recent_items).to_have_count(1)


# =========================================================================
# B2: Pre-Highlight Suggested Metric
# =========================================================================

class TestSuggestedMetricHighlight:
    def test_suggested_metric_has_class(self, page):
        """The suggested metric option should have the suggested-metric class."""
        page.goto(SERVER_URL)
        suggested = page.locator('.metric-option.suggested-metric')
        expect(suggested).to_have_count(1)
        expect(suggested).to_have_attribute(
            'data-metric-id', 'cm_net_revenue_retention'
        )

    def test_suggested_metric_visible_when_dropdown_opens(self, page):
        """Opening reclassify should scroll to show the suggested metric."""
        page.goto(SERVER_URL)
        page.locator('.btn-warning.dropdown-toggle').click()
        page.wait_for_timeout(300)
        suggested = page.locator('.metric-option.suggested-metric')
        expect(suggested).to_be_visible()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
