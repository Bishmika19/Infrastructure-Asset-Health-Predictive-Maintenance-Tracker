import { defineConfig } from '@playwright/test';
import { env } from 'node:process';

const backendEnvironment = {
  ...env,
  ALLOWED_ORIGINS: 'http://127.0.0.1:3000',
  AUTH_TOKEN_SECRET: 'playwright-accessibility-test-secret-2026-keep-out-of-production',
  SMTP_HOST: '',
  SMTP_TO: '',
};

export default defineConfig({
  testDir: './__tests__',
  testMatch: /test_.*\.spec\.ts/,
  globalSetup: './__tests__/test_global_setup.ts',
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
  webServer: [
    {
      command: 'uvicorn src.api.main:app --host 127.0.0.1 --port 8000',
      cwd: '../../backend_workspace/backend',
      env: backendEnvironment,
      reuseExistingServer: !env.CI,
      timeout: 60_000,
      url: 'http://127.0.0.1:8000/healthz',
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 3000',
      env: {
        ...env,
        VITE_API_BASE_URL: 'http://127.0.0.1:8000',
      },
      reuseExistingServer: !env.CI,
      timeout: 60_000,
      url: 'http://127.0.0.1:3000/',
    },
  ],
});
