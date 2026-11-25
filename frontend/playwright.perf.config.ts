import { defineConfig, devices } from '@playwright/test'

const port = Number(process.env.E2E_PORT ?? 4173)

// Time to content of the main screens on a seed_scale database (#71): not part of the e2e suite.
//   (cd backend && python manage.py seed_dev && python manage.py seed_scale)
//   E2E_PORT=... VITE_API_PROXY=http://localhost:<backend> npx playwright test -c playwright.perf.config.ts
export default defineConfig({
  testDir: './e2e/perf',
  testMatch: '**/*.perf.ts',
  retries: 0,
  workers: 1,
  timeout: 300_000,
  use: { ...devices['Desktop Chrome'], baseURL: `http://localhost:${port}` },
  webServer: {
    command: `npm run build && npx vite preview --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: false,
    timeout: 600_000,
  },
})
