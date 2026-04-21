// @ts-check
const { defineConfig } = require('@playwright/test');

const path = require('path');
const BOOTSTRAP_DIR = path.join(__dirname, '..', '..', 'node_modules', 'bootstrap', 'dist');

module.exports = defineConfig({
  testDir: '.',
  testMatch: '*.spec.js',
  timeout: 30000,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://localhost:5200',
    headless: true,
    channel: 'chrome',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'python3 test_server.py',
    port: 5200,
    cwd: __dirname,
    reuseExistingServer: false,
    timeout: 10000,
  },
  projects: [
    {
      name: 'chrome',
      use: { channel: 'chrome' },
    },
  ],
});
