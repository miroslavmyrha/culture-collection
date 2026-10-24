import { expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, username, watchCsp } from './support.js'

// The strain page by task (#19, #72) against the real API: a strain of this run with 230 vials
// (two batches, 200 and 30) made through the API with the session auth.setup.ts signed in.
// Strains and vials are never deleted, so the strain is this run's own, found by its name.
// Testella exempli is invented, so nothing here states a fact about a real organism.

const RUN = Date.now().toString(36)
const NAME = `Testella exempli tabs ${RUN}`

/** The run's strain with 230 unplaced vials, made as the lab's manager would through the API. */
async function strainWithManyVials(page: Page, name: string) {
  return page.evaluate(async (received) => {
    await fetch('/api/v1/auth/csrf/')
    const token = decodeURIComponent(/(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? '')
    const lab = location.pathname.split('/')[2] ?? ''
    const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': token }
    const send = async (path: string, body: unknown) => {
      const response = await fetch(`/api/v1/labs/${lab}/${path}`, { method: 'POST', headers, body: JSON.stringify(body) })
      if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`)
      const created: { public_id: string; strain?: { public_id: string; accession_number: string } | null } = await response.json()
      return created
    }
    const read = async <T>(url: string): Promise<T> => {
      const body: T = await (await fetch(url, { headers })).json()
      return body
    }
    const depositors = await read<{ results: { public_id: string }[] }>(`/api/v1/labs/${lab}/depositors/?search=E2E`)
    const uses = ['research_noncommercial', 'research_commercial', 'teaching', 'diagnostics', 'production', 'reference_qc', 'patent_deposit_related', 'redistribution']
    const deposit = await send('deposits/', {
      depositor: depositors.results[0]?.public_id,
      received_on: new Date().toLocaleDateString('sv'),
      condition: 'intact',
      name_as_received: received,
      terms: { mta: null, abs_scope: 'unknown', uses: uses.map((use) => ({ use, decision: use === 'teaching' ? 'deny' : 'permit' })) },
    })
    await send(`deposits/${deposit.public_id}/start-check/`, {})
    const taxa = await read<{ results: { public_id: string; name: string }[] }>('/api/v1/taxa/?search=exempli')
    const accepted = await send(`deposits/${deposit.public_id}/accept/`, {
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
    for (const count of [200, 30])
      await send('batches/', {
        passage: passages.results[0]?.public_id,
        method: 'cryo_minus80',
        purpose: 'seed',
        cryoprotectant: '10 % glycerol',
        preserved_on: new Date().toLocaleDateString('sv'),
        vial_count: count,
        box: null,
      })
    return { lab, id: strain.public_id, number: strain.accession_number }
  }, name)
}

test('a strain opens on its overview, its tabs switch by keyboard, every one of 230 vials is a page away, and its history reads', async ({ browser }) => {
  // 230 vials made through the API and eight pages checked with axe: 25 s on a shared machine,
  // and over the default 30 s on the first run against a fresh stack (measured twice).
  test.setTimeout(60_000)
  const context = await browser.newContext({ storageState: signedInAs(username), viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  const violations = await watchCsp(page)
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeVisible()
  const strain = await strainWithManyVials(page, NAME)

  // To the strain by the list's search, as a person finds it.
  await page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Strains' }).click()
  await page.getByRole('searchbox', { name: 'Number or name' }).fill(NAME)
  await page.keyboard.press('Enter')
  await page.getByRole('table', { name: 'Strains' }).getByRole('link', { name: strain.number, exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: strain.number })).toBeVisible()
  const tabs = page.getByRole('navigation', { name: 'Strain sections' })
  await expect(tabs.getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page')
  // The terms in force on the overview: what the strain may be used for.
  await expect(page.getByRole('table', { name: 'Uses of the terms in force' }).getByRole('row', { name: 'Teaching Not permitted' })).toBeVisible()

  // Material by keyboard: Tab from Overview to Material, Enter. The focus lands on the strain.
  await tabs.getByRole('link', { name: 'Overview' }).focus()
  await page.keyboard.press('Tab')
  await expect(tabs.getByRole('link', { name: 'Material' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(new RegExp(`/strains/${strain.id}/material$`))
  await expect(page.getByRole('heading', { level: 1, name: strain.number })).toBeFocused()
  await expect(tabs.getByRole('link', { name: 'Material' })).toHaveAttribute('aria-current', 'page')

  // 230 vials, 50 a page, never dropped: the count of all, and the last page by keyboard.
  await expect(page.getByText('230 vials', { exact: true })).toBeVisible()
  const pager = page.getByRole('navigation', { name: 'Pages of the vials' })
  await expect(pager).toContainText('1 to 50 of 230')
  const next = pager.getByRole('button', { name: 'Next' })
  await next.focus()
  for (const shown of ['51 to 100', '101 to 150', '151 to 200', '201 to 230']) {
    await page.keyboard.press('Enter')
    await expect(pager).toContainText(`${shown} of 230`)
    await expect(next).toBeFocused()
  }
  const vials = page.getByRole('table', { name: 'Vials' })
  await expect(vials.getByRole('row')).toHaveCount(31)
  await expect(vials.getByRole('row', { name: new RegExp(`^${strain.number} / 2 / 30 `) })).toBeVisible()
  await expect(next).toHaveAttribute('aria-disabled', 'true')
  // The page is in the URL: a reload keeps it.
  await page.reload()
  await expect(pager).toContainText('201 to 230 of 230')
  // One batch: from its first page, with the count of all.
  await page.getByRole('combobox', { name: 'Batch' }).selectOption({ label: 'Batch 2' })
  await expect(page.getByText('30 vials of batch 2, of 230 in all.')).toBeVisible()
  await expect(vials.getByRole('row')).toHaveCount(31)

  // History: what happened, newest first, one line each.
  await tabs.getByRole('link', { name: 'History' }).click()
  const history = page.getByRole('list', { name: 'History, newest first' })
  await expect(history).toContainText(`You added 30 vials of ${strain.number}`)
  await expect(history).toContainText(`You accessioned ${strain.number}`)
  await expect(page).toHaveTitle(`${strain.number}, history | Culture collection`)

  // Every tab at 320 px in both schemes: no sideways scroll of the page, and axe passes.
  for (const scheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme: scheme })
    await page.setViewportSize({ width: 320, height: 640 })
    for (const [tab, tail] of [['Overview', ''], ['Material', '/material'], ['Terms', '/terms'], ['History', '/history']] as const) {
      await page.goto(`/labs/${strain.lab}/strains/${strain.id}${tail}`)
      await expect(tabs.getByRole('link', { name: tab })).toHaveAttribute('aria-current', 'page')
      await expect(page.getByRole('heading', { level: 2 }).first()).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth), `${tab} ${scheme}`).toBeLessThanOrEqual(320)
      expect(await axe(page, 'body'), `${tab} ${scheme}`).toEqual([])
    }
  }
  expect(violations()).toEqual([])
  await context.close()
})
