// @ts-check
const { test, expect } = require('@playwright/test');

const TEMPLATE_ROUTES = [
  '/',
  '/reviewed-fact',
  '/rejected-fact',
  '/no-facts',
  '/images-tab-empty',
  '/images-tab',
  '/images-tab-reviewed',
];

test.describe('mock server template smoke', () => {
  for (const route of TEMPLATE_ROUTES) {
    test(`renders ${route} without server error or pageerror`, async ({ page }) => {
      const pageErrors = [];
      page.on('pageerror', (err) => pageErrors.push(err));

      const response = await page.goto(route);
      expect(response, `no response for ${route}`).not.toBeNull();
      expect(response.status(), `${route} should return 200`).toBe(200);
      expect(pageErrors, `${route} raised pageerror: ${pageErrors.map(e => e.message).join('; ')}`).toHaveLength(0);
    });
  }
});
