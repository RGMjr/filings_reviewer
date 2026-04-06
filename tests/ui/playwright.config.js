// @ts-check
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: '.',
  testMatch: '*.spec.js',
  timeout: 30000,
  use: {
    baseURL: 'http://localhost:5199',
    headless: true,
    // Intercept CDN requests and redirect to local server
    contextOptions: {
      serviceWorkers: 'block',
    },
  },
  webServer: {
    command: 'python3 test_server.py',
    port: 5199,
    cwd: __dirname,
    reuseExistingServer: false,
    timeout: 10000,
  },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
});
