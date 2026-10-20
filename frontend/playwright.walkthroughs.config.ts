import { defineConfig, devices } from '@playwright/test'

const port = Number(process.env.E2E_PORT ?? 4173)

// Role walkthroughs (#68), on demand only: `npm run walkthroughs`. They walk the real work of
// each role through the production build and measure it (e2e/walkthroughs/walk.ts), against a
// backend seeded with `seed_dev` (DEV_PASSWORD is its password). One worker, in order: the
// times are part of the result, and parallel runs would measure each other.
export default defineConfig({
  testDir: './e2e/walkthroughs',
  outputDir: 'test-results/walkthroughs',
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: [['list'], ['./e2e/walkthroughs/reporter.ts']],
  use: { baseURL: `http://localhost:${port}`, trace: 'retain-on-failure' },
  projects: [
    { name: 'walk-setup', testMatch: /walk\.setup\.ts/ },
    { name: 'walkthroughs', testMatch: /\.walk\.ts$/, use: { ...devices['Desktop Chrome'] }, dependencies: ['walk-setup'] },
  ],
  webServer: {
    command: `npm run build && npx vite preview --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
})
