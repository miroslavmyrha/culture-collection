import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, username, watchCsp } from './support.js'

// Where the lab's record and the official lists disagree (#169), against the real API. seed_e2e
// gives the E2E lab one strain of the invented Testella exempli with a risky agent (RAT)
// restriction: no entry of any list names that taxon, so the check lists it and says so. The
// seeded Bacillus subtilis strains carry no restriction and no entry names them either.

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

test('a manager sees the strain whose restriction no list names, and the page passes axe', async ({ browser }) => {
  const { page, close } = await as(browser, username)
  const csp = await watchCsp(page)
  await openClassification(page)
  await expect(page.getByRole('heading', { level: 1, name: 'Classification of E2E lab' })).toBeVisible()
  const table = page.getByRole('table', { name: 'Classification check' })
  const row = table.getByRole('row', { name: /Testella exempli/ }).first()
  await expect(row).toContainText('The strain carries a restriction no entry names')
  await expect(row).toContainText('Risky agent (RAT)')
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
