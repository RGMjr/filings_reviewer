// @ts-check
const { test, expect } = require('@playwright/test');

const path = require('path');
const fs = require('fs');

const BOOTSTRAP_DIR = path.join(__dirname, '..', '..', 'node_modules', 'bootstrap', 'dist');

// Intercept CDN requests and serve local Bootstrap files
test.beforeEach(async ({ page }) => {
  // Suppress reviewer name modal by ensuring localStorage is set
  await page.addInitScript(() => {
    localStorage.setItem('reviewer_name', 'test_reviewer');
  });

  // Serve Bootstrap from local node_modules to avoid CDN dependency
  await page.route('**/cdn.jsdelivr.net/**', async (route) => {
    const url = route.request().url();
    try {
      if (url.includes('bootstrap.bundle.min.js')) {
        const body = fs.readFileSync(path.join(BOOTSTRAP_DIR, 'js', 'bootstrap.bundle.min.js'));
        await route.fulfill({ status: 200, contentType: 'application/javascript', body });
      } else if (url.includes('bootstrap.min.css')) {
        const body = fs.readFileSync(path.join(BOOTSTRAP_DIR, 'css', 'bootstrap.min.css'));
        await route.fulfill({ status: 200, contentType: 'text/css', body });
      } else {
        await route.continue();
      }
    } catch {
      // If local bootstrap not available, let CDN request through
      await route.continue();
    }
  });
});

// =========================================================================
// 1: Filing Header
// =========================================================================
test.describe('Filing Header', () => {
  test('shows company name', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('h4.mb-0')).toContainText('Acme Corp');
  });

  test('shows accession number', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('text=0001234567-25-000001')).toBeVisible();
  });

  test('shows form type', async ({ page }) => {
    await page.goto('/');
    // Form type in the header metadata
    await expect(page.locator('text=S-1')).toBeVisible();
  });

  test('shows fact count badge', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.badge.bg-primary')).toContainText('facts');
  });

  test('shows pending count badge', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.badge.bg-warning')).toContainText('pending');
  });

  test('shows accepted count badge', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.badge.bg-success').first()).toContainText('accepted');
  });

  test('shows rejected count badge', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.badge.bg-danger').first()).toContainText('rejected');
  });

  test('shows image pending badge', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.badge.bg-info')).toContainText('img pending');
  });
});

// =========================================================================
// 2: Tab Bar
// =========================================================================
test.describe('Tab Bar', () => {
  test('text tab is active by default', async ({ page }) => {
    await page.goto('/');
    const textTab = page.locator('.nav-tabs .nav-link').first();
    await expect(textTab).toHaveClass(/active/);
    await expect(textTab).toContainText('Text');
  });

  test('images tab link is present', async ({ page }) => {
    await page.goto('/');
    const imagesTab = page.locator('.nav-tabs .nav-link').nth(1);
    await expect(imagesTab).toBeVisible();
    await expect(imagesTab).toContainText('Images');
  });

  test('text tab shows pending count', async ({ page }) => {
    await page.goto('/');
    const textTab = page.locator('.nav-tabs .nav-link').first();
    await expect(textTab).toContainText('1 pending');
  });

  test('images tab shows pending count', async ({ page }) => {
    await page.goto('/');
    const imagesTab = page.locator('.nav-tabs .nav-link').nth(1);
    await expect(imagesTab).toContainText('1 pending');
  });

  test('images tab is active when active_tab=images', async ({ page }) => {
    await page.goto('/images-tab');
    const imagesTab = page.locator('.nav-tabs .nav-link').nth(1);
    await expect(imagesTab).toHaveClass(/active/);
  });

  test('text tab is not active when on images tab', async ({ page }) => {
    await page.goto('/images-tab');
    const textTab = page.locator('.nav-tabs .nav-link').first();
    await expect(textTab).not.toHaveClass(/active/);
  });
});

// =========================================================================
// 3: Text Tab - Filters
// =========================================================================
test.describe('Filters (Text Tab)', () => {
  test('status filter select is visible', async ({ page }) => {
    await page.goto('/');
    const select = page.locator('select[name="status"]');
    await expect(select).toBeVisible();
  });

  test('status filter has All statuses option selected by default', async ({ page }) => {
    await page.goto('/');
    const select = page.locator('select[name="status"]');
    await expect(select).toHaveValue('all');
  });

  test('metric filter select is visible', async ({ page }) => {
    await page.goto('/');
    const select = page.locator('select[name="metric"]');
    await expect(select).toBeVisible();
  });

  test('sort select is visible', async ({ page }) => {
    await page.goto('/');
    const select = page.locator('select[name="sort"]');
    await expect(select).toBeVisible();
  });

  test('sort select defaults to confidence_desc', async ({ page }) => {
    await page.goto('/');
    const select = page.locator('select[name="sort"]');
    await expect(select).toHaveValue('confidence_desc');
  });

  test('fact count shown in filters row', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('text=Showing 3 of 3 facts')).toBeVisible();
  });
});

// =========================================================================
// 4: Fact Navigation Panel
// =========================================================================
test.describe('Fact Navigation Panel', () => {
  test('facts card is visible', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.card-header').filter({ hasText: 'Facts' })).toBeVisible();
  });

  test('fact nav items are listed (3 facts)', async ({ page }) => {
    await page.goto('/');
    const navItems = page.locator('.fact-nav-item');
    await expect(navItems).toHaveCount(3);
  });

  test('first fact nav item is active (current fact)', async ({ page }) => {
    await page.goto('/');
    const activeItem = page.locator('.fact-nav-item.active');
    await expect(activeItem).toHaveCount(1);
    await expect(activeItem).toContainText('cm_net_revenue_retention');
  });

  test('fact nav items show metric names', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.fact-nav-item').nth(0)).toContainText('cm_net_revenue_retention');
    await expect(page.locator('.fact-nav-item').nth(1)).toContainText('cm_total_customers');
    await expect(page.locator('.fact-nav-item').nth(2)).toContainText('cm_churn_rate');
  });

  test('fact nav items show status dots', async ({ page }) => {
    await page.goto('/');
    const dots = page.locator('.fact-nav-item .status-dot');
    await expect(dots).toHaveCount(3);
  });

  test('pending status dot has correct class', async ({ page }) => {
    await page.goto('/');
    // First fact is pending_review
    const dot = page.locator('.fact-nav-item').nth(0).locator('.status-dot');
    await expect(dot).toHaveClass(/pending_review/);
  });

  test('accepted status dot has correct class', async ({ page }) => {
    await page.goto('/');
    // Second fact is accepted
    const dot = page.locator('.fact-nav-item').nth(1).locator('.status-dot');
    await expect(dot).toHaveClass(/accepted/);
  });
});

// =========================================================================
// 5: Fact Detail Card - Content
// =========================================================================
test.describe('Fact Detail Card', () => {
  test('fact card is visible for pending fact', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#fact-detail')).toBeVisible();
  });

  test('fact card has pending CSS class', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.fact-card')).toHaveClass(/pending_review/);
  });

  test('metric ID heading is visible', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#fact-detail h5').first()).toContainText('cm_net_revenue_retention');
  });

  test('source type and extraction method shown', async ({ page }) => {
    await page.goto('/');
    // "text · keyword · Pending Review"
    await expect(page.locator('#fact-detail')).toContainText('text');
    await expect(page.locator('#fact-detail')).toContainText('keyword');
  });

  test('confidence badge shows 87%', async ({ page }) => {
    await page.goto('/');
    const badge = page.locator('.confidence-badge');
    await expect(badge).toContainText('87%');
  });

  test('confidence badge has high confidence style', async ({ page }) => {
    await page.goto('/');
    const badge = page.locator('.confidence-badge');
    await expect(badge).toHaveClass(/confidence-high/);
  });

  test('value_raw is displayed prominently', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.fs-4.fw-bold')).toContainText('115%');
  });

  test('parsed value and unit shown', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#fact-detail')).toContainText('115.0 percent');
  });

  test('period range is displayed', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#fact-detail')).toContainText('2024-01-01');
    await expect(page.locator('#fact-detail')).toContainText('2024-12-31');
  });

  test('period type shown', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#fact-detail')).toContainText('annual');
  });

  test('scope is displayed', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#fact-detail')).toContainText('company');
  });

  test('review reason alert shown', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.alert-info')).toContainText('High confidence text match');
  });

  test('evidence section is present', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('text=Evidence')).toBeVisible();
  });

  test('evidence header path breadcrumbs shown', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.breadcrumb-path')).toContainText('Financial Performance');
    await expect(page.locator('.breadcrumb-path')).toContainText('Key Metrics');
  });

  test('evidence context_before shown', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.context-text').first()).toContainText('Our net');
  });

  test('evidence highlighted_html shown in snippet', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.evidence-snippet')).toContainText('net revenue retention');
  });

  test('evidence context_after shown', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.context-text').last()).toContainText('in fiscal year 2024');
  });
});

// =========================================================================
// 6: Decision Controls - Pending Fact
// =========================================================================
test.describe('Decision Controls (Pending Fact)', () => {
  test('accept button is visible', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#btn-accept')).toBeVisible();
    await expect(page.locator('#btn-accept')).toContainText('Accept');
  });

  test('accept button shows keyboard shortcut A', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#btn-accept .kbd')).toContainText('A');
  });

  test('reject button is visible', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#btn-reject')).toBeVisible();
    await expect(page.locator('#btn-reject')).toContainText('Reject');
  });

  test('reject button shows keyboard shortcut R', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#btn-reject .kbd')).toContainText('R');
  });

  test('correct button is visible', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#btn-correct')).toBeVisible();
    await expect(page.locator('#btn-correct')).toContainText('Correct');
  });

  test('correct button shows keyboard shortcut C', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#btn-correct .kbd')).toContainText('C');
  });

  test('reviewer notes input is visible', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#reviewer-notes')).toBeVisible();
  });

  test('reviewer notes placeholder text present', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#reviewer-notes')).toHaveAttribute('placeholder', /Reviewer notes/);
  });

  test('add missed metric button is visible', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('button[data-bs-target="#addMissedMetricModal"]').first()).toBeVisible();
  });
});

// =========================================================================
// 7: Reject Form
// =========================================================================
test.describe('Reject Form', () => {
  test('reject form is hidden by default', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#reject-form')).toBeHidden();
  });

  test('clicking Reject reveals reject form', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-reject').click();
    await expect(page.locator('#reject-form')).toBeVisible();
  });

  test('clicking Reject hides correct form', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-reject').click();
    await expect(page.locator('#correct-form')).toBeHidden();
  });

  test('rejection category select is present', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-reject').click();
    const select = page.locator('#rejection-category');
    await expect(select).toBeVisible();
  });

  test('rejection category has all expected options', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-reject').click();
    const options = page.locator('#rejection-category option');
    await expect(options).toHaveCount(7); // "" + 6 categories
  });

  test('rejection reason input is present', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-reject').click();
    await expect(page.locator('#rejection-reason')).toBeVisible();
  });

  test('Confirm Reject button present', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-reject').click();
    await expect(page.locator('#reject-form button.btn-danger')).toBeVisible();
    await expect(page.locator('#reject-form button.btn-danger')).toContainText('Confirm Reject');
  });

  test('Cancel button hides reject form', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-reject').click();
    await expect(page.locator('#reject-form')).toBeVisible();
    await page.locator('#reject-form .btn-outline-secondary').click();
    await expect(page.locator('#reject-form')).toBeHidden();
  });
});

// =========================================================================
// 8: Correct Form
// =========================================================================
test.describe('Correct Form', () => {
  test('correct form is hidden by default', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#correct-form')).toBeHidden();
  });

  test('clicking Correct reveals correct form', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-correct').click();
    await expect(page.locator('#correct-form')).toBeVisible();
  });

  test('clicking Correct hides reject form', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-correct').click();
    await expect(page.locator('#reject-form')).toBeHidden();
  });

  test('metric select shows current metric as default option', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-correct').click();
    const defaultOption = page.locator('#correct-metric option[value=""]');
    await expect(defaultOption).toContainText('Keep current: cm_net_revenue_retention');
  });

  test('metric select has other available metrics', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-correct').click();
    const options = page.locator('#correct-metric option');
    // "" (keep current) + 4 other metrics (not the current one)
    await expect(options).toHaveCount(5);
  });

  test('corrected value input is present', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-correct').click();
    await expect(page.locator('#correct-value')).toBeVisible();
  });

  test('corrected value input has current value as placeholder', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-correct').click();
    // Template renders current_fact.value (Python float 115.0) as placeholder
    await expect(page.locator('#correct-value')).toHaveAttribute('placeholder', /115/);
  });

  test('notes input is present', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-correct').click();
    await expect(page.locator('#correct-notes')).toBeVisible();
  });

  test('Confirm Correct button is present', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-correct').click();
    await expect(page.locator('#correct-form button.btn-primary')).toContainText('Confirm Correct');
  });

  test('Cancel button hides correct form', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-correct').click();
    await expect(page.locator('#correct-form')).toBeVisible();
    await page.locator('#correct-form .btn-outline-secondary').click();
    await expect(page.locator('#correct-form')).toBeHidden();
  });

  test('switching from correct to reject hides correct form', async ({ page }) => {
    await page.goto('/');
    await page.locator('#btn-correct').click();
    await expect(page.locator('#correct-form')).toBeVisible();
    await page.locator('#btn-reject').click();
    await expect(page.locator('#correct-form')).toBeHidden();
    await expect(page.locator('#reject-form')).toBeVisible();
  });
});

// =========================================================================
// 9: Navigation Controls
// =========================================================================
test.describe('Navigation Controls', () => {
  test('prev button is visible', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#btn-prev')).toBeVisible();
  });

  test('prev button shows keyboard shortcut P', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#btn-prev .kbd')).toContainText('P');
  });

  test('next button is visible', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#btn-next')).toBeVisible();
  });

  test('next button shows keyboard shortcut N', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#btn-next .kbd')).toContainText('N');
  });

  test('position counter shows 1 of 3', async ({ page }) => {
    await page.goto('/');
    // Counter text is in the navigation row
    await expect(page.locator('#fact-detail')).toContainText('1 of 3');
  });
});

// =========================================================================
// 10: Already-Reviewed Fact
// =========================================================================
test.describe('Already-Reviewed Fact', () => {
  test('decision alert is visible for reviewed fact', async ({ page }) => {
    await page.goto('/reviewed-fact');
    await expect(page.locator('#decision-controls .alert-secondary')).toBeVisible();
  });

  test('decision alert shows ACCEPT in uppercase', async ({ page }) => {
    await page.goto('/reviewed-fact');
    await expect(page.locator('#decision-controls .alert-secondary')).toContainText('ACCEPT');
  });

  test('reviewer id shown in decision alert', async ({ page }) => {
    await page.goto('/reviewed-fact');
    await expect(page.locator('#decision-controls .alert-secondary')).toContainText('test_reviewer');
  });

  test('undo button is visible', async ({ page }) => {
    await page.goto('/reviewed-fact');
    await expect(page.locator('button[onclick*="undoDecision"]')).toBeVisible();
    await expect(page.locator('button[onclick*="undoDecision"]')).toContainText('Undo');
  });

  test('accept/reject/correct buttons not shown for reviewed fact', async ({ page }) => {
    await page.goto('/reviewed-fact');
    await expect(page.locator('#btn-accept')).toHaveCount(0);
    await expect(page.locator('#btn-reject')).toHaveCount(0);
    await expect(page.locator('#btn-correct')).toHaveCount(0);
  });

  test('rejected fact shows REJECT decision', async ({ page }) => {
    await page.goto('/rejected-fact');
    await expect(page.locator('#decision-controls .alert-secondary')).toContainText('REJECT');
  });

  test('rejected fact shows rejection reason', async ({ page }) => {
    await page.goto('/rejected-fact');
    await expect(page.locator('#decision-controls .alert-secondary')).toContainText('Not a metric value');
  });
});

// =========================================================================
// 11: No Facts State
// =========================================================================
test.describe('No Facts State', () => {
  test('shows No facts to review heading', async ({ page }) => {
    await page.goto('/no-facts');
    // Scope to the content card to avoid matching modal h5 elements
    await expect(page.locator('.card-body.text-center h5')).toContainText('No facts to review');
  });

  test('shows explanatory message', async ({ page }) => {
    await page.goto('/no-facts');
    await expect(page.locator('text=All facts matching your filters have been reviewed')).toBeVisible();
  });

  test('Add Missed Metric button visible in no-facts state', async ({ page }) => {
    await page.goto('/no-facts');
    await expect(page.locator('button[data-bs-target="#addMissedMetricModal"]')).toBeVisible();
  });

  test('fact nav panel shows No facts match filters', async ({ page }) => {
    await page.goto('/no-facts');
    await expect(page.locator('text=No facts match filters')).toBeVisible();
  });

  test('no fact nav items listed', async ({ page }) => {
    await page.goto('/no-facts');
    const navItems = page.locator('.fact-nav-item');
    await expect(navItems).toHaveCount(0);
  });
});

// =========================================================================
// 12: Add Missed Metric Modal
// =========================================================================
test.describe('Add Missed Metric Modal', () => {
  test('modal is not shown by default (no show class)', async ({ page }) => {
    await page.goto('/');
    // Check Bootstrap structural state — modal should not have .show class
    // (CSS display:none from Bootstrap requires it to be loaded; check class is more reliable)
    await expect(page.locator('#addMissedMetricModal')).not.toHaveClass(/\bshow\b/);
  });

  test('clicking button opens the modal', async ({ page }) => {
    await page.goto('/');
    await page.locator('button[data-bs-target="#addMissedMetricModal"]').first().click();
    await expect(page.locator('#addMissedMetricModal')).toBeVisible({ timeout: 5000 });
  });

  test('modal title is Add Missed Metric', async ({ page }) => {
    await page.goto('/');
    await page.locator('button[data-bs-target="#addMissedMetricModal"]').first().click();
    await expect(page.locator('#addMissedMetricModalLabel')).toContainText('Add Missed Metric');
  });

  test('metric select is present in modal', async ({ page }) => {
    await page.goto('/');
    await page.locator('button[data-bs-target="#addMissedMetricModal"]').first().click();
    await expect(page.locator('#missed-metric-id')).toBeVisible({ timeout: 5000 });
  });

  test('value raw input is present in modal', async ({ page }) => {
    await page.goto('/');
    await page.locator('button[data-bs-target="#addMissedMetricModal"]').first().click();
    await expect(page.locator('#missed-value-raw')).toBeVisible({ timeout: 5000 });
  });

  test('unit select is present in modal', async ({ page }) => {
    await page.goto('/');
    await page.locator('button[data-bs-target="#addMissedMetricModal"]').first().click();
    await expect(page.locator('#missed-unit')).toBeVisible({ timeout: 5000 });
  });

  test('unit select has expected options', async ({ page }) => {
    await page.goto('/');
    await page.locator('button[data-bs-target="#addMissedMetricModal"]').first().click();
    await page.locator('#missed-unit').waitFor({ state: 'visible', timeout: 5000 });
    const options = page.locator('#missed-unit option');
    // "" + percent + currency + count + ratio + basis_points + other = 7
    await expect(options).toHaveCount(7);
  });

  test('period type select is present in modal', async ({ page }) => {
    await page.goto('/');
    await page.locator('button[data-bs-target="#addMissedMetricModal"]').first().click();
    await expect(page.locator('#missed-period-type')).toBeVisible({ timeout: 5000 });
  });

  test('scope select is present in modal', async ({ page }) => {
    await page.goto('/');
    await page.locator('button[data-bs-target="#addMissedMetricModal"]').first().click();
    await expect(page.locator('#missed-scope')).toBeVisible({ timeout: 5000 });
  });

  test('modal metrics list includes available metrics', async ({ page }) => {
    await page.goto('/');
    await page.locator('button[data-bs-target="#addMissedMetricModal"]').first().click();
    await page.locator('#missed-metric-id').waitFor({ state: 'visible', timeout: 5000 });
    const options = page.locator('#missed-metric-id option');
    // "" + 5 metrics = 6
    await expect(options).toHaveCount(6);
  });
});

// =========================================================================
// 13: Decision Submission - Accept
// =========================================================================
test.describe('Decision Submission', () => {
  test('clicking Accept posts to /api/v2/decisions', async ({ page }) => {
    const requests = [];
    await page.route('/api/v2/decisions', async (route) => {
      if (route.request().method() === 'POST') {
        requests.push(await route.request().postDataJSON());
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'success',
            decision_id: 'new-decision-001',
            fact_id: 'fact-001',
            next_fact: { fact_id: 'fact-002', url: '/?fact_id=fact-002' },
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('/');
    await page.locator('#btn-accept').click();

    await page.waitForTimeout(500);
    expect(requests.length).toBe(1);
    expect(requests[0].decision).toBe('accept');
    expect(requests[0].fact_id).toBe('fact-001');
  });

  test('accept decision payload includes reviewer_id from localStorage', async ({ page }) => {
    const requests = [];
    await page.route('/api/v2/decisions', async (route) => {
      if (route.request().method() === 'POST') {
        requests.push(await route.request().postDataJSON());
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'success',
            decision_id: 'x',
            fact_id: 'fact-001',
            next_fact: null,
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('/');
    await page.locator('#btn-accept').click();

    await page.waitForTimeout(500);
    expect(requests[0].reviewer_id).toBe('test_reviewer');
  });

  test('reject decision payload includes category and reason', async ({ page }) => {
    const requests = [];
    await page.route('/api/v2/decisions', async (route) => {
      if (route.request().method() === 'POST') {
        requests.push(await route.request().postDataJSON());
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'success',
            decision_id: 'x',
            fact_id: 'fact-001',
            next_fact: null,
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('/');
    await page.locator('#btn-reject').click();
    await page.locator('#rejection-category').selectOption('not_a_metric');
    await page.locator('#rejection-reason').fill('Percentage, not a count');
    await page.locator('#reject-form button.btn-danger').click();

    await page.waitForTimeout(500);
    expect(requests[0].decision).toBe('reject');
    expect(requests[0].rejection_category).toBe('not_a_metric');
    expect(requests[0].rejection_reason).toBe('Percentage, not a count');
  });

  test('correct decision payload includes assigned_metric_id and corrected_value', async ({ page }) => {
    const requests = [];
    await page.route('/api/v2/decisions', async (route) => {
      if (route.request().method() === 'POST') {
        requests.push(await route.request().postDataJSON());
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'success',
            decision_id: 'x',
            fact_id: 'fact-001',
            next_fact: null,
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('/');
    await page.locator('#btn-correct').click();
    await page.locator('#correct-metric').selectOption('cm_arpu');
    await page.locator('#correct-value').fill('120');
    await page.locator('#correct-form button.btn-primary').click();

    await page.waitForTimeout(500);
    expect(requests[0].decision).toBe('correct');
    expect(requests[0].assigned_metric_id).toBe('cm_arpu');
    expect(requests[0].corrected_value).toBe(120);
  });

  test('review_time_seconds included in decision payload', async ({ page }) => {
    const requests = [];
    await page.route('/api/v2/decisions', async (route) => {
      if (route.request().method() === 'POST') {
        requests.push(await route.request().postDataJSON());
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'success',
            decision_id: 'x',
            fact_id: 'fact-001',
            next_fact: null,
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('/');
    await page.locator('#btn-accept').click();

    await page.waitForTimeout(500);
    expect(typeof requests[0].review_time_seconds).toBe('number');
    expect(requests[0].review_time_seconds).toBeGreaterThanOrEqual(0);
  });
});

// =========================================================================
// 14: Undo Decision
// =========================================================================
test.describe('Undo Decision', () => {
  test('clicking Undo sends DELETE to /api/v2/decisions/<id>', async ({ page }) => {
    const deleteRequests = [];
    await page.route('/api/v2/decisions/**', async (route) => {
      if (route.request().method() === 'DELETE') {
        deleteRequests.push(route.request().url());
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'success',
            message: 'Decision reverted',
            fact_id: 'fact-002',
            filing_id: 1,
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('/reviewed-fact');
    await page.locator('button[onclick*="undoDecision"]').click();

    await page.waitForTimeout(500);
    expect(deleteRequests.length).toBe(1);
    expect(deleteRequests[0]).toContain('/api/v2/decisions/decision-001');
  });
});

// =========================================================================
// 15: Images Tab
// =========================================================================
test.describe('Images Tab', () => {
  test('images tab content visible when active_tab=images', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('#review-container')).toBeVisible();
  });

  test('thumbnail sidebar present', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('.image-thumbnail-sidebar')).toBeVisible();
  });

  test('thumbnail sidebar shows image count', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('.image-thumbnail-sidebar .card-header')).toContainText('Images (2)');
  });

  test('thumbnail items listed (2 candidates)', async ({ page }) => {
    await page.goto('/images-tab');
    const items = page.locator('.thumbnail-item');
    await expect(items).toHaveCount(2);
  });

  test('first thumbnail item is active (current image)', async ({ page }) => {
    await page.goto('/images-tab');
    const activeItem = page.locator('.thumbnail-item.active');
    await expect(activeItem).toHaveCount(1);
  });

  test('reviewed thumbnail shows reviewed class', async ({ page }) => {
    await page.goto('/images-tab');
    const reviewedItem = page.locator('.thumbnail-item.reviewed');
    await expect(reviewedItem).toHaveCount(1);
  });

  test('tier badge shown for each thumbnail', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('.tier-badge').first()).toBeVisible();
  });

  test('main image display is visible', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('.image-main-display')).toBeVisible();
  });

  test('current image shows pending badge', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('.image-main-display .badge.bg-warning')).toContainText('Pending');
  });

  test('image source text shown', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('.image-main-display')).toContainText('chart1.png');
  });

  test('tier badge shown in main display', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('.image-tier-badge')).toContainText('Tier 1: Cohort');
  });

  test('decision buttons visible for pending image', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('#btn-relevant')).toBeVisible();
    await expect(page.locator('#btn-not-relevant')).toBeVisible();
    await expect(page.locator('#btn-skip')).toBeVisible();
  });

  test('Relevant button shows Y shortcut', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('#btn-relevant')).toContainText('Y');
    await expect(page.locator('#btn-relevant')).toContainText('Relevant');
  });

  test('Not Relevant button shows N shortcut', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('#btn-not-relevant')).toContainText('N');
    await expect(page.locator('#btn-not-relevant')).toContainText('Not Relevant');
  });

  test('Skip button shows S shortcut', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('#btn-skip')).toContainText('S');
    await expect(page.locator('#btn-skip')).toContainText('Skip');
  });

  test('context panel is visible', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('.image-context-panel')).toBeVisible();
  });

  test('preceding text shown in context panel', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('.preceding-text-box')).toContainText('net revenue retention');
  });

  test('keyword badges shown in context panel', async ({ page }) => {
    await page.goto('/images-tab');
    const badges = page.locator('.keyword-badge');
    await expect(badges).toHaveCount(2);
    await expect(badges.first()).toContainText('retention');
  });

  test('confidence score shown in context panel', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('.image-context-panel')).toContainText('85%');
  });

  test('detection tier explanation shown', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('.tier-explanation')).toContainText('Tier 1: Cohort');
  });

  test('image position shown in context panel', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('.image-context-panel')).toContainText('Image 1 of 2');
  });

  test('keyboard toggle button visible', async ({ page }) => {
    await page.goto('/images-tab');
    await expect(page.locator('#toggle-hints')).toBeVisible();
  });

  test('reviewed image shows decision alert', async ({ page }) => {
    await page.goto('/images-tab-reviewed');
    await expect(page.locator('.image-main-display .alert-success')).toBeVisible();
    await expect(page.locator('.image-main-display .alert-success')).toContainText('Relevant');
  });

  test('reviewed image shows chart type in decision', async ({ page }) => {
    await page.goto('/images-tab-reviewed');
    await expect(page.locator('.image-main-display .alert-success')).toContainText('Bar Chart');
  });

  test('reviewed image shows undo button', async ({ page }) => {
    await page.goto('/images-tab-reviewed');
    await expect(page.locator('#btn-undo')).toBeVisible();
  });

  test('reviewed image shows Reviewed badge', async ({ page }) => {
    await page.goto('/images-tab-reviewed');
    await expect(page.locator('.image-main-display .badge.bg-success')).toContainText('Reviewed');
  });
});

// =========================================================================
// 16: Breadcrumb Navigation
// =========================================================================
test.describe('Breadcrumb Navigation', () => {
  test('breadcrumb shows Review Filings link', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.breadcrumb')).toContainText('Review Filings');
  });

  test('breadcrumb shows company name as active item', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.breadcrumb-item.active')).toContainText('Acme Corp');
  });
});

// =========================================================================
// 17: Reviewer Name Modal (suppressed by localStorage)
// =========================================================================
test.describe('Reviewer Name Handling', () => {
  test('reviewer name modal not shown when localStorage has reviewer_name', async ({ page }) => {
    await page.goto('/');
    // When reviewer_name is set, showReviewerModal() is not called,
    // so the modal never gets the .show class
    await expect(page.locator('#reviewerModal')).not.toHaveClass(/\bshow\b/);
  });

  test('reviewer name displayed in navbar', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#reviewer-display')).toContainText('test_reviewer');
  });
});

// =========================================================================
// 18: No images state
// =========================================================================
test.describe('No Images State', () => {
  test('shows No Image Candidates message when image list is empty', async ({ page }) => {
    // Use dedicated route that renders images tab with no candidates
    await page.goto('/images-tab-empty');
    // Scope to the review container to avoid matching modal h5 elements
    await expect(page.locator('#review-container h5')).toContainText('No Image Candidates');
  });
});
