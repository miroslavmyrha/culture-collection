import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, watchCsp } from './support.js'

// Several vials into one box in one step (#77), against the real API. seed_e2e: the B. subtilis
// strain has its passage 0; e2e-curator builds storage, e2e-technician handles vials. Vials and
// units are never deleted, so each run makes a freezer of its own, named per run, preserves
// three vials in no box, and finds them by the batch it preserved.

const RUN = Date.now().toString(36)

async function as(browser: Browser, name: string) {
  const context = await browser.newContext({ storageState: signedInAs(name), viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

/** From the labs list to the Material tab of the seeded B. subtilis strain. */
async function openStrain(page: Page) {
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await page.getByRole('link', { name: 'Strains' }).click()
  await page.getByRole('row', { name: /B\. subtilis e2e seed/ }).getByRole('link').first().click()
  await page.getByRole('navigation', { name: 'Strain sections' }).getByRole('link', { name: 'Material' }).click()
  await expect(page.getByRole('heading', { level: 2, name: 'Vials' })).toBeVisible()
}

/** A call to the lab's API from the page, with the session and its CSRF token: a GET, or a POST with a body. */
async function call(page: Page, path: string, body?: Record<string, unknown>) {
  return page.evaluate(
    async ([url, payload]) => {
      await fetch('/api/v1/auth/csrf/')
      const token = /(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? ''
      const lab = location.pathname.split('/')[2] ?? ''
      const target = url.startsWith('/') ? url : `/api/v1/labs/${lab}/${url}`
      const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(token) }
      const response = payload === undefined ? await fetch(target, { headers }) : await fetch(target, { method: 'POST', headers, body: JSON.stringify(payload) })
      const json: unknown = await response.json()
      return { status: response.status, json }
    },
    [path, body] as const,
  )
}

const field = (row: unknown, key: string): string => {
  const value: unknown = typeof row === 'object' && row !== null ? Reflect.get(row, key) : undefined
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}
const results = (json: unknown): unknown[] => {
  const list: unknown = typeof json === 'object' && json !== null ? Reflect.get(json, 'results') : undefined
  return Array.isArray(list) ? list : []
}

test('a technician places three vials in no box into one box in one step, by keyboard', async ({ browser }) => {
  // The curator builds a freezer of this run with one 9 x 9 box.
  const curator = await as(browser, 'e2e-curator')
  await openStrain(curator.page)
  const freezer = await call(curator.page, 'storage-units/', { kind: 'freezer', name: `Freezer p${RUN}`, max_risk_group: 1 })
  expect(freezer.status).toBe(201)
  const rack = await call(curator.page, 'storage-units/', { kind: 'rack', name: 'Rack 1', parent: field(freezer.json, 'public_id') })
  const types = await call(curator.page, '/api/v1/box-types/')
  const nine = field(
    results(types.json).find((t) => field(t, 'name') === '81-place cryobox (9 x 9)'),
    'public_id',
  )
  expect((await call(curator.page, 'storage-units/', { kind: 'box', name: 'Box 1', parent: field(rack.json, 'public_id'), box_type: nine })).status).toBe(201)
  await curator.close()

  const { page, close } = await as(browser, 'e2e-technician')
  const violations = await watchCsp(page)
  await openStrain(page)
  const passages = await call(page, 'passages/')
  const passage = field(results(passages.json)[0], 'public_id')
  const batch = await call(page, 'batches/', { passage, method: 'lyophilised', purpose: 'seed', preserved_on: new Date().toLocaleDateString('sv'), vial_count: 3 })
  expect(batch.status).toBe(201)
  const vials = page.getByRole('table', { name: 'Vials' })
  const number = field(batch.json, 'number')
  // The strain gathers vials over the runs: the list shows only this batch's (#72, the URL's batch).
  const material = page.url().split('?')[0] ?? ''
  await page.goto(`${material}?batch=${field(batch.json, 'public_id')}`)
  await expect(vials.getByRole('checkbox')).toHaveCount(3)

  // From here on only keys: choose the three vials, open the dialog, take the next free positions.
  const where = `Freezer p${RUN} / Rack 1 / Box 1`
  for (const seq of [1, 2, 3]) {
    const box = vials.getByRole('checkbox', { name: new RegExp(` / ${number} / ${seq}$`) })
    await box.focus()
    await page.keyboard.press('Space')
    await expect(box).toBeChecked()
  }
  const open = page.getByRole('button', { name: 'Place 3 vials in a box' })
  await open.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Place 3 vials in a box' })
  const boxField = dialog.getByRole('combobox', { name: 'Box' })
  await expect(boxField).toBeFocused()
  await page.keyboard.type(where) // a native select picks the option by its text
  await expect(boxField).toHaveValue(/.+/)
  const grid = dialog.getByRole('grid', { name: `Free positions of ${where}` })
  await expect(grid).toBeVisible()
  await expect(dialog.getByText('81 of 81 positions free.')).toBeVisible()
  await expect(dialog.getByRole('list', { name: 'Where each vial goes' }).getByRole('listitem')).toHaveText([/: A1$/, /: A2$/, /: A3$/])
  expect(await axe(page, '[role="dialog"]')).toEqual([])
  await dialog.getByRole('button', { name: 'Place vials' }).focus()
  await page.keyboard.press('Enter')
  await expect(dialog).toBeHidden()
  for (const [seq, pos] of [[1, 'A1'], [2, 'A2'], [3, 'A3']] as const) {
    await expect(vials.getByRole('row', { name: new RegExp(` / ${number} / ${seq} .*${where}, ${pos}`) })).toBeVisible()
  }
  // Focus is back on the page, not on the body.
  expect(await page.evaluate(() => document.activeElement !== document.body)).toBe(true)

  // The next time the dialog opens on the same box.
  const more = await call(page, 'batches/', { passage, method: 'lyophilised', purpose: 'seed', preserved_on: new Date().toLocaleDateString('sv'), vial_count: 1 })
  const next = field(more.json, 'number')
  await page.goto(`${material}?batch=${field(more.json, 'public_id')}`)
  await vials.getByRole('checkbox', { name: new RegExp(` / ${next} / 1$`) }).check()
  await page.getByRole('button', { name: 'Place 1 vial in a box' }).click()
  const again = page.getByRole('dialog', { name: 'Place 1 vial in a box' })
  await expect(again.getByRole('combobox', { name: 'Box' })).toHaveValue(/.+/)
  await expect(again.getByText('78 of 81 positions free.')).toBeVisible()
  await expect(again.getByRole('list', { name: 'Where each vial goes' }).getByRole('listitem')).toHaveText([/: A4$/])
  await page.keyboard.press('Escape')
  await expect(again).toBeHidden()
  expect(violations()).toEqual([])
  await close()
})
