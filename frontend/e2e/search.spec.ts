import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, watchCsp } from './support.js'

// The top bar's search (#76) against the real API (seed_e2e: "E2E lab" with its seeded strain
// E2E 1, e2e-viewer and e2e-technician in it; e2e-outsider views only "E2E other lab"). The scan
// test makes a strain of this run with one vial and a barcode unique to the run, through the API
// as e2e-curator: strains and vials are never deleted, so each run finds its own. Testella
// exempli is invented, so nothing here states a fact about a real organism.

const RUN = Date.now().toString(36)

async function as(browser: Browser, username: string, options: { width?: number; colorScheme?: 'light' | 'dark' } = {}) {
  const width = options.width ?? 1280
  const context = await browser.newContext({ storageState: signedInAs(username), viewport: { width, height: width === 320 ? 640 : 900 }, colorScheme: options.colorScheme ?? 'light' })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

/** A strain of this run with one vial and the barcode, made as a curator through the API. */
async function vialWithBarcode(page: Page, name: string, barcode: string) {
  return page.evaluate(
    async ([received, code]) => {
      await fetch('/api/v1/auth/csrf/')
      const token = decodeURIComponent(/(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? '')
      const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': token }
      const read = async <T,>(url: string): Promise<T> => {
        const body: T = await (await fetch(url, { headers })).json()
        return body
      }
      const labs = await read<{ results: { public_id: string; code: string }[] }>('/api/v1/labs/')
      const lab = labs.results.find((l) => l.code === 'E2E')?.public_id ?? ''
      const send = async <T,>(path: string, body: unknown): Promise<T> => {
        const response = await fetch(`/api/v1/labs/${lab}/${path}`, { method: 'POST', headers, body: JSON.stringify(body) })
        if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`)
        const created: T = await response.json()
        return created
      }
      const depositors = await read<{ results: { public_id: string }[] }>(`/api/v1/labs/${lab}/depositors/?search=E2E`)
      const uses = ['research_noncommercial', 'research_commercial', 'teaching', 'diagnostics', 'production', 'reference_qc', 'patent_deposit_related', 'redistribution']
      const deposit = await send<{ public_id: string }>('deposits/', {
        depositor: depositors.results[0]?.public_id,
        received_on: new Date().toLocaleDateString('sv'),
        condition: 'intact',
        name_as_received: received,
        terms: { mta: null, abs_scope: 'unknown', uses: uses.map((use) => ({ use, decision: 'permit' })) },
      })
      await send(`deposits/${deposit.public_id}/start-check/`, {})
      const taxa = await read<{ results: { public_id: string; name: string }[] }>('/api/v1/taxa/?search=exempli')
      const accepted = await send<{ strain: { public_id: string; accession_number: string } | null }>(`deposits/${deposit.public_id}/accept/`, {
        taxon: taxa.results.find((t) => t.name === 'Testella exempli')?.public_id,
        identified_on: new Date().toLocaleDateString('sv'),
        identification_method: 'MALDI-TOF MS',
        risk_group: 1,
        animal_pathogenicity: 'unknown',
        plant_pathogenicity: 'unknown',
        isolation_source: '',
        country_of_origin: '',
        isolation_date: '',
        restrictions: [],
      })
      const strain = accepted.strain
      if (!strain) throw new Error('the deposit made no strain')
      const passages = await read<{ results: { public_id: string }[] }>(`/api/v1/labs/${lab}/passages/?strain=${strain.public_id}`)
      await send('batches/', { passage: passages.results[0]?.public_id, method: 'cryo_minus80', purpose: 'seed', cryoprotectant: '10 % glycerol', preserved_on: new Date().toLocaleDateString('sv'), vial_count: 2 })
      const vials = await read<{ results: { public_id: string; label: string; seq: number }[] }>(`/api/v1/labs/${lab}/vials/?strain=${strain.public_id}`)
      const second = vials.results.find((v) => v.seq === 2)
      if (!second) throw new Error('no second vial')
      await send(`vials/${second.public_id}/barcode/`, { barcode: code })
      return { number: strain.accession_number, label: second.label }
    },
    [name, barcode] as const,
  )
}

test('a viewer finds a strain by its number from the top bar and opens it by keyboard; the open search passes axe in both schemes', async ({ browser }) => {
  for (const colorScheme of ['light', 'dark'] as const) {
    const { page, close } = await as(browser, 'e2e-viewer', { colorScheme })
    const violations = await watchCsp(page)
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1, name: 'Home' })).toBeVisible()
    // `/` from the page, not from a field, puts the focus in the search.
    await page.keyboard.press('/')
    const search = page.getByRole('banner').getByRole('combobox', { name: 'Search' })
    await expect(search).toBeFocused()
    await page.keyboard.type('E2E 1')
    const results = page.getByRole('listbox', { name: 'Search results' })
    // Debounced-search waits use 10 s finds (shared machine load).
    const strains = results.getByRole('group', { name: /^Strains, \d+ strains?$/ })
    await expect(strains, 'the strains group').toBeVisible({ timeout: 10_000 })
    // The number itself first: E2E 1 before E2E 10 and up.
    await expect(strains.getByRole('option').first()).toHaveAccessibleName(/^E2E 1, E2E, Active\. Bacillus subtilis/)
    expect(await axe(page, 'header')).toEqual([])
    await page.keyboard.press('ArrowDown')
    await expect(search).toHaveAttribute('aria-activedescendant', (await strains.getByRole('option').first().getAttribute('id')) ?? 'missing')
    await page.keyboard.press('Enter')
    await expect(page.getByRole('heading', { level: 1, name: 'E2E 1' })).toBeFocused()
    await expect(page).toHaveTitle('E2E 1 | Culture collection')
    await expect(search).toHaveValue('')
    expect(violations()).toEqual([])
    await close()
  }
})

test('a technician scans a vial barcode into the search and lands on its strain with that vial', async ({ browser }) => {
  const curator = await as(browser, 'e2e-curator')
  await curator.page.goto('/')
  const made = await vialWithBarcode(curator.page, `Testella exempli search ${RUN}`, `SCAN-${RUN}`)
  await curator.close()

  const { page, close } = await as(browser, 'e2e-technician')
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'Home' })).toBeVisible()
  const search = page.getByRole('banner').getByRole('combobox', { name: 'Search' })
  await search.click()
  // A scanner types the code and Enter at once, faster than the debounce.
  await page.keyboard.type(`SCAN-${RUN}`, { delay: 5 })
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { level: 1, name: made.number })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('navigation', { name: 'Strain sections' }).getByRole('link', { name: 'Material' })).toHaveAttribute('aria-current', 'page')
  await expect(page.getByText('Only the vial you searched for.')).toBeVisible()
  const vials = page.getByRole('table', { name: 'Vials' })
  await expect(vials.getByRole('row')).toHaveCount(2)
  await expect(vials.getByRole('row').nth(1)).toContainText(made.label)
  await page.getByRole('button', { name: 'Show every vial' }).click()
  await expect(vials.getByRole('row')).toHaveCount(3)
  await expect(page.getByRole('heading', { level: 2, name: 'Vials' })).toBeFocused()
  await close()
})

test('a viewer of another lab finds nothing of E2E lab, at 320 px, where the search is a button', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-outsider', { width: 320, colorScheme: 'dark' })
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'Home' })).toBeVisible()
  const bar = page.getByRole('banner')
  await expect(bar.getByRole('combobox', { name: 'Search' })).toHaveCount(0)
  await bar.getByRole('button', { name: 'Search' }).click()
  const search = bar.getByRole('combobox', { name: 'Search' })
  await expect(search).toBeFocused()
  // Full width under the bar's controls, inside the screen.
  const box = await search.boundingBox()
  expect(box?.width ?? 0).toBeGreaterThan(260)
  for (const text of ['E2E 1', 'Testella exempli e2e regulated', 'Box R']) {
    await search.fill(text)
    await expect(bar.getByText(`No results for “${text}”.`, { exact: false })).toBeVisible({ timeout: 10_000 })
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
  expect(await axe(page, 'header')).toEqual([])
  // Escape closes the message, clears the field, then closes the search back to its button.
  await page.keyboard.press('Escape')
  await page.keyboard.press('Escape')
  await page.keyboard.press('Escape')
  await expect(bar.getByRole('button', { name: 'Search' })).toBeFocused()
  await close()
})
