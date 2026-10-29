import { defineConfig } from '@playwright/test';
import { env } from 'node:process';

export default defineConfig({
  testDir: './__tests__',
  testMatch: /test_.*\.spec\.ts/,
  forbidOnly: Boolean(env.CI),
  fullyParallel: false,
  retries: env.CI ? 1 : 0,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  outputDir: '/tmp/asset-health-playwright-results',
  use: {
    baseURL: 'http://127.0.0.1:3000',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 3000',
    reuseExistingServer: !env.CI,
    timeout: 60_000,
    url: 'http://127.0.0.1:3000/',
  },
});
