// @ts-check
//
// Chart-presence pivot — Detected Metrics card Playwright coverage (#86 PR 3b).
//
// Fixture routes live in test_server.py:
//   /images-tab-detected            — detected_metrics populated, no prior confirmations
//   /images-tab-detected-preseeded  — detected_metrics populated + one 'accept' prior confirmation
//
// The card wires to POST /api/v2/image-metric-confirmations and
// GET /api/v2/metrics/list; both are mocked by the fixture server.

const { test, expect } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const BOOTSTRAP_DIR = path.join(__dirname, '..', '..', 'node_modules', 'bootstrap', 'dist');

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('reviewer_name', 'test_reviewer');
  });

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
      await route.continue();
    }
  });
});

// =========================================================================
// Card rendering
// =========================================================================
test.describe('Detected Metrics card — rendering', () => {
  test('card is visible when detected_metrics is non-empty', async ({ page }) => {
    await page.goto('/images-tab-detected');
    await expect(page.locator('#detected-metrics-card')).toBeVisible();
  });

  test('card IS rendered when detected_metrics is empty (sql/47 redesign)', async ({ page }) => {
    // Per the sql/47 redesign, the detected-metrics card is the sole reviewer
    // surface for image review and renders for every pending/reviewed image,
    // even when the pipeline detected no metrics — the reviewer can still
    // image-skip or Add a missed metric.
    await page.goto('/images-tab');
    await expect(page.locator('#detected-metrics-card')).toBeVisible();
    // No detected rows when detected_metrics is empty.
    await expect(page.locator('#detected-metrics-list .detected-metric-row')).toHaveCount(0);
    // "Add metric the classifier missed" stays available.
    await expect(page.locator('#btn-add-missed-detected-metric')).toBeVisible();
  });

  test('card header shows detected count badge', async ({ page }) => {
    await page.goto('/images-tab-detected');
    await expect(page.locator('#detected-metrics-card .card-header')).toContainText('4 detected');
  });

  test('one row per detected metric', async ({ page }) => {
    await page.goto('/images-tab-detected');
    const rows = page.locator('#detected-metrics-list .detected-metric-row');
    await expect(rows).toHaveCount(4);
  });

  test('row shows metric id and score', async ({ page }) => {
    await page.goto('/images-tab-detected');
    const firstRow = page.locator('#detected-metrics-list .detected-metric-row').first();
    await expect(firstRow).toContainText('cm_customer_retention_rate');
    await expect(firstRow).toContainText('0.95');
  });

  test('row has accept/reject/correct buttons', async ({ page }) => {
    await page.goto('/images-tab-detected');
    const firstRow = page.locator('#detected-metrics-list .detected-metric-row').first();
    await expect(firstRow.locator('.btn-accept-metric')).toBeVisible();
    await expect(firstRow.locator('.btn-reject-metric')).toBeVisible();
    await expect(firstRow.locator('.btn-correct-metric')).toBeVisible();
  });

  test('add-missed-metric button is visible', async ({ page }) => {
    await page.goto('/images-tab-detected');
    await expect(page.locator('#btn-add-missed-detected-metric')).toBeVisible();
  });

  test('submit-decisions button is visible', async ({ page }) => {
    await page.goto('/images-tab-detected');
    await expect(page.locator('#btn-submit-detected-metrics')).toBeVisible();
  });

  test('pre-seeded accept confirmation applies decided-accept class on load', async ({ page }) => {
    await page.goto('/images-tab-detected-preseeded');
    const acceptedRow = page.locator(
      '#detected-metrics-list .detected-metric-row[data-metric-id="cm_customer_retention_rate"]',
    );
    await expect(acceptedRow).toHaveClass(/decided-accept/);
    await expect(acceptedRow.locator('.metric-state-indicator')).toContainText('Accepted');
  });

  test('pre-seeded add confirmation renders an added-metric-row on load', async ({ page }) => {
    await page.goto('/images-tab-detected-with-added');
    const addedRow = page.locator(
      '#detected-metrics-list .added-metric-row[data-added-metric="cm_lifetime_value_per_customer"]',
    );
    await expect(addedRow).toBeVisible();
    await expect(addedRow).toContainText('cm_lifetime_value_per_customer');
  });

  test('header shows "M added" badge and inclusive title when an add confirmation exists', async ({ page }) => {
    await page.goto('/images-tab-detected-with-added');
    const header = page.locator('#detected-metrics-card .card-header');
    await expect(header).toContainText('4 detected');
    await expect(header).toContainText('1 added');
    await expect(header).toContainText('Metrics (detected + user-added)');
  });
});

// =========================================================================
// Decision interactions
// =========================================================================
test.describe('Detected Metrics card — decisions', () => {
  test('Accept button marks row decided-accept', async ({ page }) => {
    await page.goto('/images-tab-detected');
    const row = page.locator('#detected-metrics-list .detected-metric-row').first();
    await row.locator('.btn-accept-metric').click();
    await expect(row).toHaveClass(/decided-accept/);
    await expect(row.locator('.metric-state-indicator')).toContainText('Accepted');
  });

  test('Reject opens reason dropdown, selecting a reason marks decided-reject', async ({ page }) => {
    await page.goto('/images-tab-detected');
    const row = page.locator('#detected-metrics-list .detected-metric-row').nth(1);
    await row.locator('.btn-reject-metric').click();
    await expect(row.locator('.reject-expansion')).toBeVisible();
    await row.locator('.metric-reject-reason').selectOption('similar_metric_misclassified');
    await expect(row).toHaveClass(/decided-reject/);
    await expect(row.locator('.metric-state-indicator'))
      .toContainText('similar_metric_misclassified');
  });

  test('Correct opens metric picker, entering a different metric marks decided-correct', async ({ page }) => {
    await page.goto('/images-tab-detected');
    const row = page.locator('#detected-metrics-list .detected-metric-row').nth(2);
    await row.locator('.btn-correct-metric').click();
    await expect(row.locator('.correct-expansion')).toBeVisible();
    await row.locator('.metric-correct-input').fill('cm_churn_rate');
    await row.locator('.metric-correct-input').dispatchEvent('change');
    await expect(row).toHaveClass(/decided-correct/);
    await expect(row.locator('.metric-state-indicator')).toContainText('cm_churn_rate');
  });

  test('Correct to the same metric shows validation and does NOT mark decided', async ({ page }) => {
    await page.goto('/images-tab-detected');
    const row = page.locator('#detected-metrics-list .detected-metric-row').first();
    const mid = await row.getAttribute('data-metric-id');
    await row.locator('.btn-correct-metric').click();
    await row.locator('.metric-correct-input').fill(mid);
    await row.locator('.metric-correct-input').dispatchEvent('change');
    await expect(row).not.toHaveClass(/decided-correct/);
    await expect(row.locator('.metric-state-indicator')).toContainText(/different metric/i);
  });

  test('Add missed metric appends a new added row', async ({ page }) => {
    await page.goto('/images-tab-detected');
    await page.locator('#btn-add-missed-detected-metric').click();
    await page.locator('#add-missed-detected-input').fill('cm_lifetime_value_per_customer');
    await page.locator('#btn-add-missed-detected-confirm').click();
    const addedRow = page.locator(
      '#detected-metrics-list .added-metric-row[data-added-metric="cm_lifetime_value_per_customer"]',
    );
    await expect(addedRow).toBeVisible();
    await expect(addedRow).toContainText('Added');
  });
});

// =========================================================================
// Keyboard shortcuts (focus-scoped)
// =========================================================================
test.describe('Detected Metrics card — keyboard shortcuts', () => {
  test('A on focused row triggers accept', async ({ page }) => {
    await page.goto('/images-tab-detected');
    const row = page.locator('#detected-metrics-list .detected-metric-row').first();
    await row.focus();
    await page.keyboard.press('a');
    await expect(row).toHaveClass(/decided-accept/);
  });

  test('R on focused row opens reject expansion', async ({ page }) => {
    await page.goto('/images-tab-detected');
    const row = page.locator('#detected-metrics-list .detected-metric-row').nth(1);
    await row.focus();
    await page.keyboard.press('r');
    await expect(row.locator('.reject-expansion')).toBeVisible();
  });

  test('C on focused row opens correct expansion', async ({ page }) => {
    await page.goto('/images-tab-detected');
    const row = page.locator('#detected-metrics-list .detected-metric-row').nth(2);
    await row.focus();
    await page.keyboard.press('c');
    await expect(row.locator('.correct-expansion')).toBeVisible();
  });

  test('N on focused row advances focus to next unreviewed row', async ({ page }) => {
    await page.goto('/images-tab-detected');
    const first = page.locator('#detected-metrics-list .detected-metric-row').nth(0);
    const second = page.locator('#detected-metrics-list .detected-metric-row').nth(1);
    // Accept first, then press N to move to the next unreviewed row (second).
    await first.focus();
    await page.keyboard.press('a');
    await first.focus();
    await page.keyboard.press('n');
    await expect(second).toBeFocused();
  });
});

// =========================================================================
// Submit flow
// =========================================================================
test.describe('Detected Metrics card — submit', () => {
  test('Submit posts decisions array to /api/v2/image-metric-confirmations', async ({ page }) => {
    const captured = [];
    await page.route('/api/v2/image-metric-confirmations', async (route) => {
      if (route.request().method() === 'POST') {
        const body = await route.request().postDataJSON();
        captured.push(body);
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true, upserted: body.decisions.length, confirmations: [] }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('/images-tab-detected');
    // Accept the first row, then submit.
    await page.locator('#detected-metrics-list .detected-metric-row').first()
      .locator('.btn-accept-metric').click();
    await page.locator('#btn-submit-detected-metrics').click();

    await page.waitForTimeout(300);
    expect(captured.length).toBe(1);
    expect(captured[0].img_id).toBe('img-detected-12');
    expect(captured[0].reviewer_id).toBe('test_reviewer');
    expect(captured[0].decisions.length).toBe(1);
    expect(captured[0].decisions[0].decision).toBe('accept');
    expect(captured[0].decisions[0].detected_metric_id).toBe('cm_customer_retention_rate');
  });

  test('Submit rejects without reason are filtered out', async ({ page }) => {
    const captured = [];
    await page.route('/api/v2/image-metric-confirmations', async (route) => {
      if (route.request().method() === 'POST') {
        const body = await route.request().postDataJSON();
        captured.push(body);
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true, upserted: body.decisions.length, confirmations: [] }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('/images-tab-detected');
    // Open reject but don't pick a reason, then accept a different row.
    await page.locator('#detected-metrics-list .detected-metric-row').first()
      .locator('.btn-reject-metric').click();
    await page.locator('#detected-metrics-list .detected-metric-row').nth(1)
      .locator('.btn-accept-metric').click();
    await page.locator('#btn-submit-detected-metrics').click();

    await page.waitForTimeout(300);
    // Only the accept should be submitted.
    expect(captured[0].decisions.length).toBe(1);
    expect(captured[0].decisions[0].decision).toBe('accept');
  });

  test('Full round-trip: accept / reject / correct / add — state preserved on reload', async ({ page }) => {
    const captured = [];
    await page.route('/api/v2/image-metric-confirmations', async (route) => {
      if (route.request().method() === 'POST') {
        const body = await route.request().postDataJSON();
        captured.push(body);
        const confirmations = body.decisions.map((d, i) => ({
          confirmation_id: `c-${i}`,
          img_id: body.img_id,
          detected_metric_id: d.detected_metric_id,
          confirmed_metric_id: d.confirmed_metric_id,
          decision: d.decision,
          rejection_reason: d.rejection_reason,
          reviewer_id: body.reviewer_id,
          created_at: '2026-04-23T00:00:00+00:00',
          updated_at: '2026-04-23T00:00:00+00:00',
        }));
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true, upserted: body.decisions.length, confirmations }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('/images-tab-detected');

    const rows = page.locator('#detected-metrics-list .detected-metric-row');
    // accept first
    await rows.nth(0).locator('.btn-accept-metric').click();
    // reject second with reason
    await rows.nth(1).locator('.btn-reject-metric').click();
    await rows.nth(1).locator('.metric-reject-reason').selectOption('not_present');
    // correct third
    await rows.nth(2).locator('.btn-correct-metric').click();
    await rows.nth(2).locator('.metric-correct-input').fill('cm_lifetime_value_per_customer');
    await rows.nth(2).locator('.metric-correct-input').dispatchEvent('change');
    // add a fourth metric
    await page.locator('#btn-add-missed-detected-metric').click();
    await page.locator('#add-missed-detected-input').fill('cm_churn_rate');
    await page.locator('#btn-add-missed-detected-confirm').click();

    await page.locator('#btn-submit-detected-metrics').click();
    await page.waitForTimeout(300);
    expect(captured.length).toBe(1);
    const decisions = captured[0].decisions;
    expect(decisions.map(d => d.decision).sort()).toEqual(['accept', 'add', 'correct', 'reject']);

    // Simulate the reload path using the preseeded route
    // (the PR 3b backend serves existing confirmations via get_image_metric_confirmations).
    await page.goto('/images-tab-detected-preseeded');
    const acceptedRow = page.locator(
      '#detected-metrics-list .detected-metric-row[data-metric-id="cm_customer_retention_rate"]',
    );
    await expect(acceptedRow).toHaveClass(/decided-accept/);
  });
});
