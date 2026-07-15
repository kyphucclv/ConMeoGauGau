import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: 'line',
  use: {
    baseURL: 'http://127.0.0.1:8012',
    channel: 'chrome',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run e2e:prepare && powershell -NoProfile -ExecutionPolicy Bypass -File ../scripts/run_e2e_server.ps1',
    url: 'http://127.0.0.1:8012/api/health/live',
    reuseExistingServer: false,
    timeout: 120_000,
  },
})
