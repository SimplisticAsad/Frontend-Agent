import { defineConfig } from '@playwright/test';

const chromium = process.env.PW_CHROMIUM_PATH;

export default defineConfig({
  testDir: './tests',
  outputDir: './test-results/artifacts',
  fullyParallel: true,
  retries: 0,
  workers: process.env.CI ? 2 : undefined,
  timeout: 30_000,
  expect: { timeout: 7_500 },
  reporter: [['list'], ['json', { outputFile: process.env.PW_JSON_OUT ?? 'test-results/results.json' }]],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'off',
    launchOptions: chromium ? { executablePath: chromium } : {},
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects: [
    { name: 'e2e', testDir: './tests/e2e', testMatch: /.*\.spec\.ts/ },
    { name: 'visual', testDir: './tests/visual', testMatch: /.*\.spec\.ts/ },
  ],
});
