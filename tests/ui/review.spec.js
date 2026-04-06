// @ts-check
const { test, expect } = require('@playwright/test');

const path = require('path');
const fs = require('fs');

const BOOTSTRAP_DIR = path.join(__dirname, '..', '..', 'node_modules', 'bootstrap', 'dist');

// Intercept CDN requests and serve local Bootstrap files
test.beforeEach(async ({ page }) => {
  await page.route('**/cdn.jsdelivr.net/**', async (route) => {
    const url = route.request().url();
    if (url.includes('bootstrap.bundle.min.js')) {
      const body = fs.readFileSync(path.join(BOOTSTRAP_DIR, 'js', 'bootstrap.bundle.min.js'));
      await route.fulfill({ status: 200, contentType: 'application/javascript', body });
    } else if (url.includes('bootstrap.min.css')) {
      const body = fs.readFileSync(path.join(BOOTSTRAP_DIR, 'css', 'bootstrap.min.css'));
      await route.fulfill({ status: 200, contentType: 'text/css', body });
    } else {
      await route.continue();
    }
  });
});

// =========================================================================
// A1: Collapsible Filing Header
// =========================================================================
test.describe('A1: Collapsible Filing Header', () => {
  test('has collapse toggle button', async ({ page }) => {
    await page.goto('/');
    const toggle = page.locator('.filing-header-toggle');
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute('data-bs-toggle', 'collapse');
    await expect(toggle).toHaveAttribute('data-bs-target', '#filing-header-details');
  });

  test('metadata section visible by default', async ({ page }) => {
    await page.goto('/');
    const details = page.locator('#filing-header-details');
    await expect(details).toBeVisible();
  });

  test('clicking toggle collapses metadata', async ({ page }) => {
    await page.goto('/');
    const toggle = page.locator('.filing-header-toggle');
    await toggle.click();
    const details = page.locator('#filing-header-details');
    await expect(details).not.toBeVisible({ timeout: 2000 });
  });

  test('clicking toggle again re-expands metadata', async ({ page }) => {
    await page.goto('/');
    const toggle = page.locator('.filing-header-toggle');
    await toggle.click();
    const details = page.locator('#filing-header-details');
    await expect(details).not.toBeVisible({ timeout: 2000 });
    await toggle.click();
    await expect(details).toBeVisible({ timeout: 2000 });
  });

  test('form type badge always visible', async ({ page }) => {
    await page.goto('/');
    const badge = page.locator('#filing-header-card .badge.bg-secondary');
    await expect(badge).toBeVisible();
    await expect(badge).toHaveText('S-1');
  });

  test('breadcrumb visible when header collapsed', async ({ page }) => {
    await page.goto('/');
    const toggle = page.locator('.filing-header-toggle');
    await toggle.click();
    await expect(page.locator('#filing-header-details')).not.toBeVisible({ timeout: 2000 });
    const breadcrumb = page.locator('#filing-header-card .breadcrumb');
    await expect(breadcrumb).toBeVisible();
    await expect(breadcrumb).toContainText('Acme Corp');
  });
});

// =========================================================================
// A2: Compact Value + Metric Bar
// =========================================================================
test.describe('A2: Compact Value + Metric Bar', () => {
  test('compact bar exists and is visible', async ({ page }) => {
    await page.goto('/');
    const bar = page.locator('.compact-value-metric-bar');
    await expect(bar).toBeVisible();
  });

  test('displays formatted parsed value', async ({ page }) => {
    await page.goto('/');
    const value = page.locator('.compact-bar-value');
    await expect(value).toBeVisible();
    await expect(value).toContainText('$1,234,567.89');
  });

  test('displays suggested metric name', async ({ page }) => {
    await page.goto('/');
    const metric = page.locator('.compact-bar-metric');
    await expect(metric).toBeVisible();
    await expect(metric).toContainText('Cm Net Revenue Retention');
  });

  test('displays confidence badge with detailed tooltip', async ({ page }) => {
    await page.goto('/');
    const confidence = page.locator('.compact-bar-confidence');
    await expect(confidence).toBeVisible();
    await expect(confidence).toContainText('High');
    await expect(confidence).toContainText('85%');
    await expect(confidence).toHaveAttribute('title', /Strong keyword match/);
  });

  test('shows raw text and keyword in details row', async ({ page }) => {
    await page.goto('/');
    const details = page.locator('.compact-bar-details');
    await expect(details).toBeVisible();
    await expect(details).toContainText('1,234,567.89');
    await expect(details).toContainText('revenue retention');
  });

  test('old separate Extracted Value heading is gone', async ({ page }) => {
    await page.goto('/');
    const headings = page.getByText('Extracted Value', { exact: true });
    await expect(headings).toHaveCount(0);
  });

  test('old separate Suggested Metric heading is gone', async ({ page }) => {
    await page.goto('/');
    const headings = page.getByText('Suggested Metric', { exact: true });
    await expect(headings).toHaveCount(0);
  });

  test('feature badges in compact bar', async ({ page }) => {
    await page.goto('/');
    // Mock has contains_definition_language=True
    const badge = page.locator('.compact-bar-badge').first();
    await expect(badge).toBeVisible();
    await expect(badge).toContainText('Definition');
  });
});

// =========================================================================
// A3: Decision Form Merged into Candidate Card
// =========================================================================
test.describe('A3: Decision Form Merged into Candidate Card', () => {
  test('single candidate-card on page', async ({ page }) => {
    await page.goto('/');
    const cards = page.locator('.candidate-card');
    await expect(cards).toHaveCount(1);
  });

  test('decision form is inside candidate card', async ({ page }) => {
    await page.goto('/');
    const form = page.locator('.candidate-card #decision-form');
    await expect(form).toBeVisible();
  });

  test('accept button visible', async ({ page }) => {
    await page.goto('/');
    const accept = page.locator('[data-decision="accept"]');
    await expect(accept).toBeVisible();
  });

  test('reject dropdown visible', async ({ page }) => {
    await page.goto('/');
    const reject = page.locator('.btn-danger.dropdown-toggle');
    await expect(reject).toBeVisible();
  });

  test('reclassify dropdown visible', async ({ page }) => {
    await page.goto('/');
    const reclassify = page.locator('.btn-warning.dropdown-toggle');
    await expect(reclassify).toBeVisible();
  });

  test('hr separator between context and decision', async ({ page }) => {
    await page.goto('/');
    const hr = page.locator('.candidate-card hr');
    await expect(hr).toHaveCount(1);
  });

  test('already-reviewed shows inline in candidate card', async ({ page }) => {
    await page.goto('/reviewed');
    const alert = page.locator('.candidate-card .alert-info');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText('Already Reviewed');
  });
});

// =========================================================================
// B1: Recently-Used Metrics
// =========================================================================
test.describe('B1: Recently-Used Metrics', () => {
  test('no recent section with empty localStorage', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => localStorage.removeItem('recentMetrics'));
    await page.locator('.btn-warning.dropdown-toggle').click();
    // Wait for dropdown to be visible before checking
    await expect(page.locator('.metric-selector.show')).toBeVisible({ timeout: 2000 });
    const recent = page.locator('.recent-metrics-section');
    await expect(recent).toHaveCount(0);
  });

  test('recent section appears with seeded data', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.setItem('recentMetrics',
        JSON.stringify(['cm_arpu', 'cm_churn_rate']));
    });
    await page.reload();
    await page.locator('.btn-warning.dropdown-toggle').click();
    const recent = page.locator('.recent-metrics-section').first();
    await expect(recent).toBeVisible({ timeout: 2000 });
    // Check header and items
    await expect(page.locator('.recent-metrics-section .dropdown-header')).toContainText('Recent');
    await expect(page.locator('.recent-metrics-section .metric-option')).toHaveCount(2);
  });

  test('skips invalid metric IDs', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.setItem('recentMetrics',
        JSON.stringify(['cm_nonexistent', 'cm_arpu']));
    });
    await page.reload();
    await page.locator('.btn-warning.dropdown-toggle').click();
    const recent = page.locator('.recent-metrics-section').first();
    await expect(recent).toBeVisible({ timeout: 2000 });
    // Only cm_arpu should appear
    const recentItems = page.locator('.recent-metrics-section .metric-option');
    await expect(recentItems).toHaveCount(1);
  });

  test('recent items are inside .metric-list for keyboard nav', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.setItem('recentMetrics',
        JSON.stringify(['cm_arpu']));
    });
    await page.reload();
    await page.locator('.btn-warning.dropdown-toggle').click();
    // Verify recent items are children of .metric-list
    const insideList = page.locator('.metric-list .recent-metrics-section .metric-option');
    await expect(insideList).toHaveCount(1);
  });
});

// =========================================================================
// B2: Pre-Highlight Suggested Metric
// =========================================================================
test.describe('B2: Pre-Highlight Suggested Metric', () => {
  test('suggested metric has highlighted class', async ({ page }) => {
    await page.goto('/');
    const suggested = page.locator('.metric-option.suggested-metric');
    await expect(suggested).toHaveCount(1);
    await expect(suggested).toHaveAttribute(
      'data-metric-id', 'cm_net_revenue_retention'
    );
  });

  test('suggested metric visible when dropdown opens', async ({ page }) => {
    await page.goto('/');
    await page.locator('.btn-warning.dropdown-toggle').click();
    const suggested = page.locator('.metric-option.suggested-metric');
    await expect(suggested).toBeVisible({ timeout: 2000 });
  });
});
