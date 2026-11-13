import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, username, watchCsp } from './support.js'

// Where the lab's record and the official lists disagree (#169), against the real API. seed_e2e
// reads its classifications out of the list data files by entry code. The E. coli K-12 strain is
// recorded at group 1 where annex 7 entry 1.73 states group 2 (it excepts non-pathogenic
// strains), so the check lists it and shows the reason the collection recorded. The B. subtilis
// strains show up through their old name Vibrio subtilis, which a genus entry of annex 7 names.

async function as(browser: Browser, user: string) {
  const context = await browser.newContext({ storageState: signedInAs(user), viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

const openClassification = async (page: Page) => {
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeVisible()
  await page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Classification', exact: true }).click()
}

test('a manager sees the strain recorded below its entry, with the reason, and the page passes axe', async ({ browser }) => {
  const { page, close } = await as(browser, username)
  const csp = await watchCsp(page)
  await openClassification(page)
  await expect(page.getByRole('heading', { level: 1, name: 'Classification of E2E lab' })).toBeVisible()
  const table = page.getByRole('table', { name: 'Classification check' })
  const row = table.getByRole('row', { name: /Escherichia coli/ }).first()
  await expect(row).toContainText('Annex 7 states another risk group: the entry states risk group 2, the strain has 1')
  await expect(row).toContainText('entry 1.73')
  await expect(row).toContainText('Accepted by the collection: Annex 7 of 361/2007 Sb. lists the species')
  expect(await axe(page, 'main')).toEqual([])
  expect(csp()).toEqual([])
  await close()
})

test('a viewer gets no tab and is told the check is the managers’', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-viewer')
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  const tabs = page.getByRole('navigation', { name: 'Lab sections' })
  await expect(tabs.getByRole('link', { name: 'Strains' })).toBeVisible()
  await expect(tabs.getByRole('link', { name: 'Classification', exact: true })).toHaveCount(0)
  await page.goto(new URL(page.url()).pathname.replace(/\/?$/, '/classification'))
  await expect(page.getByText('Only managers see where the classification disagrees with the official lists.')).toBeVisible()
  await close()
})
