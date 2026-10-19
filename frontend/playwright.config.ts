import { defineConfig, devices } from '@playwright/test'

const port = Number(process.env.E2E_PORT ?? 4173)

// Runs against the production build served by `vite preview` with the production
// CSP header, proxying /api to a running backend (VITE_API_PROXY).
export default defineConfig({
  testDir: './e2e',
  // One retry on CI only: a flaky test shows up as "flaky" in the report instead of
  // failing the run. Locally a failure stays a failure.
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: `http://localhost:${port}`, trace: 'retain-on-failure' },
  // setup signs each e2e user in once (e2e/auth.setup.ts), so the run stays under the login
  // throttle; every spec runs after it and reuses those sessions.
  projects: [
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    { name: 'chromium', use: { ...devices['Desktop Chrome'] }, dependencies: ['setup'] },
  ],
  webServer: {
    command: `npm run build && npx vite preview --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
})
