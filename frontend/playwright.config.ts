import { defineConfig, devices } from '@playwright/test'

const port = Number(process.env.E2E_PORT ?? 4173)

// Runs against the production build served by `vite preview` with the production
// CSP header, proxying /api to a running backend (VITE_API_PROXY).
export default defineConfig({
  testDir: './e2e',
  // The role walkthroughs run on demand with their own config (npm run walkthroughs).
  testIgnore: ['walkthroughs/**'],
  // One retry on CI only: a flaky test shows up as "flaky" in the report instead of
  // failing the run. Locally a failure stays a failure.
  retries: process.env.CI ? 1 : 0,
  // One budget for every test and every expect, in place of a timeout in each spec (#60). Measured over
  // the whole suite (75 tests) against a fresh stack: the slowest test took 36 s with 4 busy processes on
  // the 4 cores and 44 s with 8, and the slowest expect waited 1.5 s with 8. A test gets 150 s, 3.4 times
  // the slowest at 8 (the 30 s default failed it). An expect gets 15 s: 10 times the slowest wait seen and
  // 3 times the old default, because deposits.spec.ts:126 failed at 5 s on a strain page still loading, a
  // wait that 3 loaded runs did not reproduce.
  timeout: 150_000,
  expect: { timeout: 15_000 },
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
    // The command builds the app first, which is real work: on a busy machine it ran past 120 s (#60).
    timeout: 600_000,
  },
})
