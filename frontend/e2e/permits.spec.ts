import { type Browser, expect, test } from '@playwright/test'
import { axe, signedInAs, username, watchCsp } from './support.js'

// The permits screen (#82) against the real API. seed_e2e gives "E2E lab" one permit, an invented
// SÚJB permit for VRAT that ended in 2025, so its row reads the same on any day and the lab still
// holds no valid permit (deposits.spec.ts relies on that). The e2e user manages the lab,
// e2e-viewer views it. Nothing here changes data.

test.describe.configure({ timeout: 120_000 })

async function as(browser: Browser, user: string) {
  const context = await browser.newContext({ storageState: signedInAs(user), viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

test('a manager opens the permits from the lab tabs and reads them; a viewer has no tab and no list', async ({ browser }) => {
  const manager = await as(browser, username)
  const page = manager.page
  const violations = await watchCsp(page)
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeVisible()
  const labUrl = page.url()

  await page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Permits', exact: true }).click()
  const heading = page.getByRole('heading', { level: 1, name: 'Permits of E2E lab' })
  await expect(heading).toBeFocused()
  await expect(page).toHaveTitle('Permits of E2E lab | Culture collection')
  await expect(page.getByText(/This list is read only: staff record a permit and its end in the Django admin\./)).toBeVisible()

  const row = page.getByRole('table', { name: 'Permits', exact: true }).getByRole('row', { name: /SÚJB\/DEV\/E2E\/1/ })
  await expect(row).toContainText('Permit to handle highly risky agents (VRAT)')
  await expect(row).toContainText('SÚJB SÚJB/DEV/E2E/1 (invented example)')
  await expect(row).toContainText('2025-01-01')
  await expect(row).toContainText('Ended')
  await expect(row).toContainText('Ended on 2025-06-30: Surrendered (invented example).')
  await expect(page.getByRole('main').getByRole('button')).toHaveCount(0)
  expect(await axe(page, 'main')).toEqual([])
  expect(violations()).toEqual([])
  await manager.close()

  const viewer = await as(browser, 'e2e-viewer')
  await viewer.page.goto(labUrl)
  const tabs = viewer.page.getByRole('navigation', { name: 'Lab sections' })
  await expect(tabs.getByRole('link', { name: 'Strains', exact: true })).toBeVisible()
  await expect(tabs.getByRole('link', { name: 'Permits', exact: true })).toHaveCount(0)
  await viewer.page.goto(`${labUrl}/permits`)
  await expect(viewer.page.getByText("Only managers see the lab's permits.")).toBeVisible()
  await expect(viewer.page.getByRole('table')).toHaveCount(0)
  await viewer.close()
})
