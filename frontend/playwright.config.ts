import { defineConfig, devices } from '@playwright/test';

// The dev server proxies /v1 to the API, so tests use ONE origin and the app's
// own network path. Hitting the API directly would bypass the proxy and stop
// testing the seam that broke in production.
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173';

export default defineConfig({
  testDir: './e2e',
  // The pipeline is ~7s locally and slower in CI; these are ceilings, not sleeps.
  timeout: 90_000,
  expect: { timeout: 20_000 },
  // Serial by default: the suite shares one database and one worker queue.
  // Parallelism here buys seconds and costs determinism.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run dev',
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
