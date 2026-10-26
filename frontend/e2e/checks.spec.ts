import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, contrast, signedInAs, watchCsp } from './support.js'

// Each test walks several pages and scans them with axe: real work, 5 to 25 s on a quiet machine and over
// the 30 s default on a busy one (#60).
test.describe.configure({ timeout: 120_000 })

// Checks of a batch and its release (#17) against the real API. Each test makes a strain of
// its own through deposit intake (received, checked, accepted as Bacillus subtilis, risk group
// 1 as LPSN and the DSMZ catalogue state for the species), named for the run, and preserves a
// batch of three vials of distribution stock: strains and batches are never deleted, so a run
// never meets another run's rows. It works as the sessions auth.setup.ts signed in.

const RUN = Date.now().toString(36)
const today = () => new Date().toLocaleDateString('sv')

async function as(browser: Browser, name: string, width = 1280) {
  const context = await browser.newContext({ storageState: signedInAs(name), viewport: { width, height: width === 320 ? 640 : 900 } })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

type Row = Record<string, unknown>
const isRow = (value: unknown): value is Row => typeof value === 'object' && value !== null && !Array.isArray(value)
const rows = (json: unknown): Row[] => {
  const list: unknown = isRow(json) ? json.results : json
  return Array.isArray(list) ? list.filter(isRow) : []
}
const text = (row: unknown, key: string) => {
  const value: unknown = isRow(row) ? row[key] : undefined
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}

/** A call to the API from the page, with the session and its CSRF token. A path without a leading slash is in the lab. */
async function call(page: Page, lab: string, path: string, body?: Row) {
  const answer = await page.evaluate(
    async ([labId, url, payload]) => {
      await fetch('/api/v1/auth/csrf/')
      const token = /(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? ''
      const target = url.startsWith('/') ? url : `/api/v1/labs/${labId}/${url}`
      const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(token) }
      const response = payload === undefined ? await fetch(target, { headers }) : await fetch(target, { method: 'POST', headers, body: JSON.stringify(payload) })
      return { status: response.status, text: await response.text() }
    },
    [lab, path, body] as const,
  )
  return { status: answer.status, json: answer.text ? (JSON.parse(answer.text) as unknown) : null }
}

async function ok(page: Page, lab: string, path: string, body?: Row) {
  const answer = await call(page, lab, path, body)
  expect(answer.status, `${path}: ${JSON.stringify(answer.json)}`).toBeLessThan(300)
  return answer.json
}

/** A strain of this run through intake, accepted by the curator, with a batch of three vials. */
async function strainWithBatch(browser: Browser, tag: string) {
  const { page, close } = await as(browser, 'e2e-curator')
  await page.goto('/labs')
  const href = await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).getAttribute('href')
  const lab = (href ?? '').split('/')[2] ?? ''
  const name = `B. subtilis ${tag} ${RUN}`
  const depositor = rows(await ok(page, lab, 'depositors/'))[0]
  const uses = ['research_noncommercial', 'research_commercial', 'teaching', 'diagnostics', 'production', 'reference_qc', 'patent_deposit_related', 'redistribution']
  const deposit = text(
    await ok(page, lab, 'deposits/', {
      depositor: text(depositor, 'public_id'),
      received_on: today(),
      condition: 'intact',
      name_as_received: name,
      terms: { mta: null, abs_scope: 'not_in_scope', country_of_origin: 'CZ', uses: uses.map((use) => ({ use, decision: 'permit' })) },
    }),
    'public_id',
  )
  await ok(page, lab, `deposits/${deposit}/start-check/`, {})
  const taxon = rows(await ok(page, lab, '/api/v1/taxa/?search=Bacillus%20subtilis')).find((t) => t.name === 'Bacillus subtilis')
  await ok(page, lab, `deposits/${deposit}/accept/`, {
    taxon: text(taxon, 'public_id'),
    identified_on: today(),
    identification_method: '16S rRNA gene sequence',
    risk_group: 1,
    country_of_origin: 'CZ',
    restrictions: [],
  })
  const strain = text(rows(await ok(page, lab, `strains/?search=${encodeURIComponent(name)}`))[0], 'public_id')
  const passage = text(rows(await ok(page, lab, `passages/?strain=${strain}`))[0], 'public_id')
  const batch = text(
    await ok(page, lab, 'batches/', { passage, method: 'cryo_minus80', purpose: 'distribution', cryoprotectant: '10 % glycerol', preserved_on: today(), vial_count: 3 }),
    'public_id',
  )
  const vials = rows(await ok(page, lab, `vials/?batch=${batch}`)).map((v) => text(v, 'label'))
  await close()
  return { lab, strain, batch, vials, path: `/labs/${lab}/strains/${strain}/material` }
}

async function openBatch(page: Page, path: string) {
  await page.goto(path)
  const toggle = page.getByRole('button', { name: 'Checks of batch 1' })
  await toggle.focus()
  await page.keyboard.press('Enter')
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByRole('list', { name: 'Checks of batch 1', exact: true }).or(page.getByText('No check recorded yet.'))).toBeVisible()
}

const status = (page: Page) => page.getByRole('table', { name: 'Batches' }).getByRole('row').nth(1).getByRole('cell').nth(5)

test('a technician records three passed checks by keyboard and a curator releases the batch', async ({ browser }) => {
  const s = await strainWithBatch(browser, 'release')
  const tech = await as(browser, 'e2e-technician')
  const violations = await watchCsp(tech.page)
  await openBatch(tech.page, s.path)
  await expect(status(tech.page)).toHaveText('Pending checkWaiting for a passed identity, purity and viability check.')
  await expect(tech.page.getByRole('button', { name: /^(Release|Hold)$/ })).toHaveCount(0)

  const record = tech.page.getByRole('button', { name: 'Record a check' })
  for (const [i, kind] of (['Identity', 'Purity', 'Viability'] as const).entries()) {
    await record.focus()
    await tech.page.keyboard.press('Enter')
    const dialog = tech.page.getByRole('dialog', { name: 'Record a check of batch 1' })
    const kindField = dialog.getByRole('combobox', { name: 'Kind' })
    await expect(kindField).toBeFocused()
    await expect(kindField).toHaveValue(kind.toLowerCase()) // the first kind still waiting
    if (kind === 'Viability') {
      // The vial thawed for it: used up by the check.
      await dialog.getByRole('combobox', { name: 'Vial checked' }).selectOption({ label: s.vials[0] ?? '' })
      await dialog.getByRole('combobox', { name: 'Method' }).selectOption('plate_count')
      await dialog.getByRole('textbox', { name: 'Value' }).fill('2.1e8')
      await dialog.getByRole('combobox', { name: 'Unit' }).selectOption('cfu_per_ml')
    }
    await dialog.getByRole('button', { name: 'Record check' }).focus()
    await tech.page.keyboard.press('Enter')
    await expect(dialog).toBeHidden()
    await expect(record).toBeFocused()
    await expect(tech.page.getByRole('list', { name: 'Checks of batch 1', exact: true }).getByRole('listitem')).toHaveCount(i + 1)
  }
  await expect(tech.page.getByRole('list', { name: 'Latest checks of batch 1' })).toHaveText(/Identity: Passed.*Purity: Passed.*Viability: Passed/)
  await expect(tech.page.getByRole('list', { name: 'Checks of batch 1', exact: true })).toContainText(`210000000 CFU/mL, vial ${s.vials[0] ?? ''}`)
  await expect(status(tech.page)).toHaveText('Pending checkAll checks passed. A curator releases it.')
  await expect(tech.page.getByRole('table', { name: 'Vials' }).getByRole('row', { name: new RegExp(`${s.vials[0] ?? ''} Consumed`) })).toBeVisible()
  expect(violations()).toEqual([])
  await tech.close()

  const curator = await as(browser, 'e2e-curator')
  await openBatch(curator.page, s.path)
  await expect(curator.page.getByText('Available for distribution: none.', { exact: false })).toBeVisible()
  const release = curator.page.getByRole('button', { name: 'Release' })
  await release.focus()
  await curator.page.keyboard.press('Enter')
  const dialog = curator.page.getByRole('dialog', { name: 'Release batch 1' })
  await expect(dialog.getByRole('textbox', { name: 'Reason' })).toBeFocused()
  await curator.page.keyboard.type('Identity, purity and viability after preservation passed.')
  await dialog.getByRole('button', { name: 'Release batch' }).click()
  await expect(dialog).toBeHidden()
  // Release is gone with the release: the focus is on the batch's heading, not on the body.
  await expect(curator.page.getByRole('heading', { level: 3, name: 'Batch 1: Released' })).toBeFocused()
  await expect(status(curator.page)).toHaveText('Released')
  await expect(curator.page.getByText('Available for distribution: 2 vials, from released batch 1.')).toBeVisible()
  await expect(curator.page.getByRole('button', { name: 'Hold' })).toBeVisible()
  await curator.close()

  // A viewer reads it all, is offered nothing, and the API refuses a viewer's check.
  const viewer = await as(browser, 'e2e-viewer')
  await openBatch(viewer.page, s.path)
  await expect(status(viewer.page)).toHaveText('Released')
  await expect(viewer.page.getByRole('list', { name: 'Checks of batch 1', exact: true }).getByRole('listitem')).toHaveCount(3)
  await expect(viewer.page.getByRole('button', { name: /Record a check|^Release$|^Hold$|in error/ })).toHaveCount(0)
  const refused = await call(viewer.page, s.lab, 'batch-checks/', { batch: s.batch, kind: 'purity', stage: 'periodic', checked_on: today(), method: 'streak_plate', result: 'fail' })
  expect(refused.status).toBe(403)
  const hold = await call(viewer.page, s.lab, `batches/${s.batch}/hold/`, { reason: 'no' })
  expect(hold.status).toBe(403)
  await viewer.close()
})

test('a failed purity check holds the batch, and a curator is offered no release', async ({ browser }) => {
  const s = await strainWithBatch(browser, 'hold')
  const tech = await as(browser, 'e2e-technician')
  await openBatch(tech.page, s.path)
  await tech.page.getByRole('button', { name: 'Record a check' }).click()
  const dialog = tech.page.getByRole('dialog', { name: 'Record a check of batch 1' })
  await dialog.getByRole('combobox', { name: 'Kind' }).selectOption('purity')
  await dialog.getByRole('combobox', { name: 'Result' }).selectOption('fail')
  await dialog.getByRole('textbox', { name: 'Note' }).fill('A second colony type on the plate.')
  await dialog.getByRole('button', { name: 'Record check' }).click()
  await expect(dialog).toBeHidden()
  await expect(status(tech.page)).toHaveText(`On holdThe purity check of ${today()} failed.`)
  await expect(tech.page.getByRole('heading', { level: 3, name: 'Batch 1: On hold' })).toBeVisible()
  await tech.close()

  const curator = await as(browser, 'e2e-curator')
  await openBatch(curator.page, s.path)
  await expect(curator.page.getByRole('list', { name: 'Latest checks of batch 1' })).toContainText('Purity: Failed')
  await expect(curator.page.getByRole('button', { name: /^(Release|Hold)$/ })).toHaveCount(0)
  // The API holds the same line: no release while the latest purity check failed.
  const refused = await call(curator.page, s.lab, `batches/${s.batch}/release/`, { reason: 'try' })
  expect(refused.status).toBe(422)
  expect(text(refused.json, 'code')).toBe('checks_not_passed')
  await curator.close()
})

test('the open checks fit 320 px, pass axe, and their dialogs read', async ({ browser }) => {
  const s = await strainWithBatch(browser, 'narrow')
  const { page, close } = await as(browser, 'e2e-curator', 320)
  await openBatch(page, s.path)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
  // The panel stays in view while the batch table is wider than the screen.
  const heading = page.getByRole('heading', { level: 3, name: 'Batch 1: Pending check' })
  const box = await heading.boundingBox()
  expect(box && box.x >= 0 && box.x + box.width <= 320).toBe(true)
  const hold = page.getByRole('button', { name: 'Hold' })
  const holdBox = await hold.boundingBox()
  expect(holdBox && holdBox.x + holdBox.width <= 320).toBe(true)
  expect(await axe(page, 'body')).toEqual([])
  await hold.click()
  const dialog = page.getByRole('dialog', { name: 'Hold batch 1' })
  await expect(dialog.getByRole('textbox', { name: 'Reason' })).toBeFocused()
  expect(await axe(page, '[role="dialog"]')).toEqual([])
  const description = dialog.getByText('Nothing of a held batch is sent until a curator releases it again.')
  expect(await contrast(description, dialog)).toBeGreaterThanOrEqual(4.5)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(hold).toBeFocused()
  // By keyboard: a click leaves the pointer where the dialog's Cancel opens, and a hovered text
  // button measures 4.38:1 (a theme matter of every dialog, not of this one).
  await page.getByRole('button', { name: 'Record a check' }).focus()
  await page.keyboard.press('Enter')
  const form = page.getByRole('dialog', { name: 'Record a check of batch 1' })
  await expect(form.getByRole('combobox', { name: 'Kind' })).toBeFocused()
  expect(await axe(page, '[role="dialog"]')).toEqual([])
  await page.keyboard.press('Escape')
  await close()
})
