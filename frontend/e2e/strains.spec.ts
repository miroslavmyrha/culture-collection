import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, watchCsp } from './support.js'

// The strain registry against the real API (seed_e2e: e2e-curator and e2e-viewer in "E2E lab",
// a few taxa, no permits, and one strain from an accepted deposit, B. subtilis, risk group 1).
// Strains come from accepted deposits: deposits.spec.ts adds them. These tests change no data.
// It works as the sessions auth.setup.ts signed in.


async function as(browser: Browser, username: string, width = 1280) {
  const context = await browser.newContext({ storageState: signedInAs(username), viewport: { width, height: width === 320 ? 640 : 900 } })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

/** From the labs list to the seeded lab's strains, by its links. */
async function openStrains(page: Page) {
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await page.getByRole('link', { name: 'Strains' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Strains of E2E lab' })).toBeVisible()
}

const fitsWidth = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth)

test('a viewer reads strains but cannot add one, in the screen and at the API', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-viewer')
  await openStrains(page)
  await expect(page.getByRole('row', { name: /B\. subtilis e2e seed/ })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Receive a deposit' })).toHaveCount(0)
  // The server decides, not the hidden link: strains are no longer created at this URL.
  const status = await page.evaluate(async () => {
    await fetch('/api/v1/auth/csrf/')
    const token = /(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? ''
    const lab = location.pathname.split('/')[2] ?? ''
    const response = await fetch(`/api/v1/labs/${lab}/strains/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(token) },
      body: '{}',
    })
    return response.status
  })
  expect(status).toBe(405)
  await close()
})

test('the strain pages fit 320 px without scrolling sideways and pass axe', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-curator', 320)
  const violations = await watchCsp(page)
  await openStrains(page)
  expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
  expect(await axe(page, 'body')).toEqual([])
  const first = page.getByRole('table', { name: 'Strains' }).getByRole('link').first()
  await first.click()
  await expect(page.getByRole('heading', { level: 2, name: 'Identification history' })).toBeVisible()
  expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
  expect(await axe(page, 'body')).toEqual([])
  await page.getByRole('button', { name: 'Change risk group' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  expect(await fitsWidth(page)).toBeLessThanOrEqual(320)
  expect(await axe(page, '[role="dialog"]')).toEqual([])
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Change risk group' })).toBeFocused()
  expect(violations()).toEqual([])
  await close()
})
