import type { Page } from '@playwright/test'

// Seeded by `python manage.py seed_e2e` (backend/cultures/labs/management/commands/seed_e2e.py),
// locally and in CI: the user manages the lab "E2E lab", e2e-colleague is in no lab.
export const username = process.env.E2E_USERNAME ?? 'e2e-user'
export const password = process.env.E2E_PASSWORD ?? 'e2e correct horse battery'

/**
 * Collects CSP and Trusted Types violations from every document the page loads: console errors
 * and securitypolicyviolation events. The binding sends each event to the test at once, so a
 * reload or goto does not drop what an earlier document reported (a window variable read at
 * the end only sees the last document). Chrome words Trusted Types errors as "requires
 * 'TrustedHTML' assignment", hence the wider pattern.
 */
export async function watchCsp(page: Page) {
  const seen: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'error' && /Content Security Policy|Trusted ?(Type|HTML|Script)/i.test(msg.text())) seen.push(msg.text())
  })
  await page.exposeBinding('reportCspViolation', (_source, text: unknown) => {
    seen.push(String(text))
  })
  await page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (e) => {
      const report: unknown = Reflect.get(window, 'reportCspViolation')
      if (typeof report === 'function') void report(`${e.effectiveDirective} ${e.blockedURI}`)
    })
  })
  return () => seen
}

