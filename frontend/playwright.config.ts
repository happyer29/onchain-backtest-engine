import { defineConfig } from '@playwright/test';
// Browser tests run against the packaged Python server and a new hermetic data root.
const port = process.env.BACKTEST_BROWSER_PORT ?? '8795';
export default defineConfig({
  testDir: './e2e', fullyParallel: false, workers: 1, timeout: 30_000,
  use: { baseURL: `http://127.0.0.1:${port}`, viewport: { width: 1440, height: 1050 },
    // An installed Chrome can be selected when the managed Chromium download is unavailable.
    channel: process.env.BACKTEST_BROWSER_CHANNEL || undefined, trace: 'retain-on-failure' },
  webServer: { command: '../.venv/bin/python scripts/browser-server.py', url: `http://127.0.0.1:${port}/api/v1/health`, timeout: 60_000, reuseExistingServer: false },
});
