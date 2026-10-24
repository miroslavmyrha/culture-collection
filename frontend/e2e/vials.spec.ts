import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, username, watchCsp } from './support.js'

// Batches and vials against the real API (seed_e2e: the B. subtilis strain from the seeded
// deposit has its passage 0; a regulated Testella exempli strain has two vials in E2E freezer >
// Rack 1 > Box R; the e2e user holds the lab's location grant, e2e-curator does not). Vials and
// units are never deleted, so each run preserves into a freezer of its own, named uniquely per
// run, and finds its vials by that name. It works as the sessions auth.setup.ts signed in.

const RUN = Date.now().toString(36)

async function as(browser: Browser, name: string, width = 1280) {
  const context = await browser.newContext({ storageState: signedInAs(name), viewport: { width, height: width === 320 ? 640 : 900 } })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

/** From the labs list to the material of a strain of the seeded lab, by its links and its name as received. */
async function openStrain(page: Page, received: RegExp) {
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await page.getByRole('link', { name: 'Strains' }).click()
  await page.getByRole('row', { name: received }).getByRole('link').first().click()
  // The material is the strain page's Material tab (#19).
  await page.getByRole('navigation', { name: 'Strain sections' }).getByRole('link', { name: 'Material' }).click()
  await expect(page.getByRole('heading', { level: 2, name: 'Vials' })).toBeVisible()
}

/** A POST to the API from the page, with the session and its CSRF token. */
function post(page: Page, path: string, body: Record<string, unknown>) {
  return page.evaluate(
    async ([url, payload]) => {
      await fetch('/api/v1/auth/csrf/')
      const token = /(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? ''
      const lab = location.pathname.split('/')[2] ?? ''
      const response = await fetch(`/api/v1/labs/${lab}/${url}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(token) },
        body: JSON.stringify(payload),
      })
      const created: { public_id: string } = await response.json()
      return { status: response.status, body: created }
    },
    [path, body] as const,
  )
}

test('a curator preserves a batch into a box, moves a vial and quarantines it, by keyboard', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-curator')
  const violations = await watchCsp(page)
  await openStrain(page, /B\. subtilis e2e seed/)
  // A freezer, rack and box of this run, through the storage API (storage.spec.ts tests the screens).
  const freezer = await post(page, 'storage-units/', { kind: 'freezer', name: `Freezer v${RUN}`, max_risk_group: 1 })
  expect(freezer.status).toBe(201)
  const rack = await post(page, 'storage-units/', { kind: 'rack', name: 'Rack 1', parent: freezer.body.public_id })
  const types = await page.evaluate(async () => {
    const list: { results: { public_id: string; name: string }[] } = await (await fetch('/api/v1/box-types/')).json()
    return list.results
  })
  const nine = types.find((t) => t.name === '81-place cryobox (9 x 9)')?.public_id
  expect((await post(page, 'storage-units/', { kind: 'box', name: 'Box 1', parent: rack.body.public_id, box_type: nine })).status).toBe(201)
  await page.reload()
  await expect(page.getByRole('heading', { level: 2, name: 'Vials' })).toBeVisible()
  const where = `Freezer v${RUN} / Rack 1 / Box 1`

  // From here on only keys.
  await page.getByRole('button', { name: 'Preserve a batch' }).focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: /^Preserve a batch of E2E/ })
  await expect(dialog.getByRole('combobox', { name: 'Passage' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('combobox', { name: 'Method' })).toBeFocused()
  await page.keyboard.type('Frozen in liquid') // a native select picks the option by its text
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('textbox', { name: 'Protectant' })).toBeFocused()
  await page.keyboard.type('10 % glycerol')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('textbox', { name: 'Number of vials' })).toBeFocused()
  await page.keyboard.type('2')
  await page.keyboard.press('Tab')
  const box = dialog.getByRole('combobox', { name: 'Box' })
  await expect(box).toBeFocused()
  await page.keyboard.type(where)
  await expect(box).toHaveValue(/.+/)
  await page.keyboard.press('Tab') // Cancel
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('button', { name: 'Preserve batch' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('button', { name: 'Preserve a batch' })).toBeFocused()

  const vials = page.getByRole('table', { name: 'Vials' })
  const first = vials.getByRole('row', { name: new RegExp(`${where}, A1`) })
  await expect(first).toBeVisible()
  await expect(vials.getByRole('row', { name: new RegExp(`${where}, A2`) })).toBeVisible()
  const label = (await first.getByRole('cell').first().textContent()) ?? ''

  await page.getByRole('button', { name: `Move vial ${label}` }).focus()
  await page.keyboard.press('Enter')
  const move = page.getByRole('dialog', { name: `Move vial ${label}` })
  await expect(move.getByRole('combobox', { name: 'Box' })).toBeFocused()
  await page.keyboard.press('Tab')
  await page.keyboard.type('C')
  await page.keyboard.press('Tab')
  await page.keyboard.type('3')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Enter')
  await expect(move).toBeHidden()
  await expect(vials.getByRole('row', { name: new RegExp(`${label}.*${where}, C3`) })).toBeVisible()

  await page.getByRole('button', { name: `Change the state of vial ${label}` }).focus()
  await page.keyboard.press('Enter')
  const state = page.getByRole('dialog', { name: `Change the state of vial ${label}` })
  await expect(state.getByRole('combobox', { name: 'New state' })).toBeFocused()
  await page.keyboard.type('Quarantined')
  await page.keyboard.press('Tab')
  await page.keyboard.type('contamination suspected')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Enter')
  await expect(state).toBeHidden()
  // Quarantined keeps its place.
  await expect(vials.getByRole('row', { name: new RegExp(`${label}.*Quarantined.*${where}, C3`) })).toBeVisible()
  expect(violations()).toEqual([])
  await close()
})

test('a viewer reads the batches and vials but is offered no bench work, and the API agrees', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-viewer')
  await openStrain(page, /B\. subtilis e2e seed/)
  await expect(page.getByRole('list', { name: 'Passages from the deposit' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Preserve a batch|Subculture|Move|Place|Change the state|Revive/ })).toHaveCount(0)
  const passage = await page.evaluate(async () => {
    const lab = location.pathname.split('/')[2] ?? ''
    const list: { results: { public_id: string }[] } = await (await fetch(`/api/v1/labs/${lab}/passages/`)).json()
    return list.results[0]?.public_id ?? ''
  })
  expect((await post(page, 'passages/', { source_passage: passage })).status).toBe(403)
  await close()
})

test('a regulated strain hides its places from a curator without the grant; a holder reveals one', async ({ browser }) => {
  const curator = await as(browser, 'e2e-curator')
  await openStrain(curator.page, /Testella exempli e2e regulated/)
  const hidden = curator.page.getByRole('table', { name: 'Vials' })
  await expect(hidden.getByRole('row', { name: /Hidden: regulated strain/ })).toHaveCount(2)
  await expect(curator.page.getByText(/Box R/)).toHaveCount(0)
  await expect(curator.page.getByRole('button', { name: /Reveal the location/ })).toHaveCount(0)
  await curator.close()

  const keeper = await as(browser, username)
  const violations = await watchCsp(keeper.page)
  await openStrain(keeper.page, /Testella exempli e2e regulated/)
  const reveal = keeper.page.getByRole('button', { name: /Reveal the location of vial .* \/ 1$/ })
  await expect(keeper.page.getByText(/Box R/)).toHaveCount(0)
  await reveal.focus()
  await keeper.page.keyboard.press('Enter')
  await expect(keeper.page.getByText('E2E freezer / Rack 1 / Box R, A1')).toBeVisible()
  const hide = keeper.page.getByRole('button', { name: /Hide the location of vial .* \/ 1$/ })
  await expect(hide).toBeFocused()
  expect(await axe(keeper.page, 'main')).toEqual([])
  await keeper.page.keyboard.press('Enter')
  await expect(keeper.page.getByText(/Box R/)).toHaveCount(0)
  expect(violations()).toEqual([])
  await keeper.close()
})

test('the strain page with its material fits 320 px and passes axe, a dialog too', async ({ browser }) => {
  const { page, close } = await as(browser, 'e2e-curator', 320)
  await openStrain(page, /B\. subtilis e2e seed/)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
  expect(await axe(page, 'body')).toEqual([])
  await page.getByRole('button', { name: 'Preserve a batch' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('combobox', { name: 'Box' })).toBeVisible()
  expect(await axe(page, '[role="dialog"]')).toEqual([])
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await close()
})
