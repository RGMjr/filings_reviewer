// @ts-check
const { defineConfig } = require('@playwright/test');

const path = require('path');
const BOOTSTRAP_DIR = path.join(__dirname, '..', '..', 'node_modules', 'bootstrap', 'dist');

module.exports = defineConfig({
  testDir: '.',
  testMatch: '*.spec.js',
  timeout: 30000,
  use: {
    baseURL: 'http://localhost:5200',
    headless: true,
    channel: 'chrome',
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
