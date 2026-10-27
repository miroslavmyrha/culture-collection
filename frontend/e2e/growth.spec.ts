import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, watchCsp } from './support.js'

test.describe.configure({ timeout: 120_000 })

// Growth media and conditions (#79, walkthroughs V9 and T6) against the real API. A curator adds a
// medium of this run to the lab's list, sets how the seeded B. subtilis strain is grown, and a
// technician revives a vial of a batch made for this run: the new passage starts from the
// strain's conditions and a second revival overrides them. A viewer reads the result. Media are
// never deleted, so each run names its own.

const RUN = Date.now().toString(36)
const MEDIUM = `Medium g${RUN}`
const OTHER = `Medium o${RUN}`

async function as(browser: Browser, user: string) {
  const context = await browser.newContext({ storageState: signedInAs(user), viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  return { page, close: () => context.close() }
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

async function openLab(page: Page) {
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeVisible()
}

async function openStrain(page: Page) {
  await openLab(page)
  await page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Strains', exact: true }).click()
  await page.getByRole('row', { name: /B\. subtilis e2e seed/ }).getByRole('link').first().click()
}

const section = (page: Page, tab: string) => page.getByRole('navigation', { name: 'Strain sections' }).getByRole('link', { name: tab })

test('V9 and T6: a curator lists a medium and sets the conditions, a technician revives with and without an override, a viewer reads them', async ({ browser }) => {
  const curator = await as(browser, 'e2e-curator')
  const page = curator.page
  const violations = await watchCsp(page)

  // The lab's list of media: two of this run, one retired.
  await openLab(page)
  await page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Media', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Media of E2E lab' })).toBeVisible()
  for (const [name, reference] of [[MEDIUM, 'DSMZ medium 1'], [OTHER, '']] as const) {
    await page.getByRole('button', { name: 'Add a medium' }).click()
    const dialog = page.getByRole('dialog', { name: 'Add a medium' })
    await dialog.getByRole('textbox', { name: 'Name' }).fill(name)
    await dialog.getByRole('textbox', { name: 'Composition reference' }).fill(reference)
    await dialog.getByRole('button', { name: 'Add medium' }).click()
    await expect(dialog).toBeHidden()
  }
  const media = page.getByRole('table', { name: 'Media' })
  await expect(media.getByRole('row', { name: new RegExp(`${MEDIUM}.*DSMZ medium 1.*Active`) })).toBeVisible()
  expect(await axe(page, 'main')).toEqual([])

  // The strain: medium, temperature range and atmosphere, with a reason (V9 reads them after).
  await openStrain(page)
  await page.getByRole('button', { name: /^Actions for / }).click()
  await page.getByRole('menuitem', { name: 'Change growth conditions' }).click()
  const growth = page.getByRole('dialog', { name: /^Growth conditions of / })
  await growth.getByRole('combobox', { name: 'Medium' }).selectOption({ label: MEDIUM })
  await growth.getByRole('textbox', { name: 'Temperature °C' }).fill('25')
  await growth.getByRole('textbox', { name: 'Up to °C' }).fill('30')
  await growth.getByRole('combobox', { name: 'Atmosphere' }).selectOption({ label: 'Aerobic' })
  await growth.getByRole('button', { name: 'Save growth conditions' }).click()
  await expect(growth.getByText(/reason/i).first()).toBeVisible() // a change without a reason is refused
  await growth.getByRole('textbox', { name: 'Reason' }).fill(`Catalogue conditions, run ${RUN}.`)
  await growth.getByRole('button', { name: 'Save growth conditions' }).click()
  await expect(growth).toBeHidden()
  const facts = page.getByRole('region', { name: 'Growth conditions' })
  await expect(facts).toContainText(`${MEDIUM}, DSMZ medium 1`)
  await expect(facts).toContainText('25 to 30 °C')
  await expect(facts).toContainText('Aerobic')

  // Stock for this run: an unplaced batch of two vials from passage 0, made through the API.
  const strainUrl = page.url()
  const strain = strainUrl.split('/').at(-1) ?? ''
  const zero = await page.evaluate(async (id) => {
    const lab = location.pathname.split('/')[2] ?? ''
    const list: { results: { public_id: string; number: number }[] } = await (await fetch(`/api/v1/labs/${lab}/passages/?strain=${id}`)).json()
    return list.results.find((p) => p.number === 0)?.public_id ?? ''
  }, strain)
  const batch = await post(page, 'batches/', { passage: zero, method: 'cryo_minus80', purpose: 'distribution', cryoprotectant: '10 % glycerol', preserved_on: new Date().toLocaleDateString('sv'), vial_count: 2 })
  expect(batch.status).toBe(201)
  const labels = await page.evaluate(async (id) => {
    const lab = location.pathname.split('/')[2] ?? ''
    const list: { results: { label: string; seq: number }[] } = await (await fetch(`/api/v1/labs/${lab}/vials/?batch=${id}&limit=200`)).json()
    return list.results.toSorted((a, b) => a.seq - b.seq).map((v) => v.label)
  }, batch.body.public_id)
  expect(labels).toHaveLength(2)
  expect(violations()).toEqual([])
  await curator.close()

  // T6: the technician revives a vial. The form starts from the strain's conditions and records them.
  const technician = await as(browser, 'e2e-technician')
  const bench = technician.page
  await bench.goto(strainUrl)
  await section(bench, 'Material').click()
  await bench.getByRole('button', { name: `Actions for vial ${labels[0]}` }).click()
  await bench.getByRole('menuitem', { name: 'Revive' }).click()
  const revive = bench.getByRole('alertdialog', { name: `Revive vial ${labels[0]}?` })
  await expect(revive.getByRole('combobox', { name: 'Medium' }).locator('option:checked')).toHaveText(MEDIUM)
  await expect(revive.getByRole('textbox', { name: 'Temperature °C' })).toHaveValue('25')
  await expect(revive.getByRole('textbox', { name: 'Up to °C' })).toHaveValue('30')
  await expect(revive.getByRole('combobox', { name: 'Atmosphere' }).locator('option:checked')).toHaveText('Aerobic')
  await revive.getByRole('button', { name: 'Revive vial' }).click()
  await expect(revive).toBeHidden()
  const passagesList = bench.getByRole('list', { name: 'Passages from the deposit' })
  await expect(passagesList.getByText(`Grown on: ${MEDIUM}, 25 to 30 °C, Aerobic`)).toHaveCount(1)

  // The second revival overrides the strain's conditions.
  await bench.getByRole('button', { name: `Actions for vial ${labels[1]}` }).click()
  await bench.getByRole('menuitem', { name: 'Revive' }).click()
  const again = bench.getByRole('alertdialog', { name: `Revive vial ${labels[1]}?` })
  await again.getByRole('combobox', { name: 'Medium' }).selectOption({ label: OTHER })
  await again.getByRole('textbox', { name: 'Temperature °C' }).fill('37')
  await again.getByRole('textbox', { name: 'Up to °C' }).fill('')
  await again.getByRole('combobox', { name: 'Atmosphere' }).selectOption({ label: 'Anaerobic' })
  await again.getByRole('button', { name: 'Revive vial' }).click()
  await expect(again).toBeHidden()
  await expect(passagesList.getByText(`Grown on: ${OTHER}, 37 °C, Anaerobic`)).toHaveCount(1)
  await technician.close()

  // V9: a viewer finds the strain's conditions on its page.
  const viewer = await as(browser, 'e2e-viewer')
  await viewer.page.goto(strainUrl)
  const read = viewer.page.getByRole('region', { name: 'Growth conditions' })
  await expect(read).toContainText(`${MEDIUM}, DSMZ medium 1`)
  await expect(read).toContainText('25 to 30 °C')
  await expect(read).toContainText('Aerobic')
  await section(viewer.page, 'Material').click()
  await expect(viewer.page.getByRole('list', { name: 'Passages from the deposit' }).getByText(`Grown on: ${OTHER}, 37 °C, Anaerobic`)).toBeVisible()
  await expect(viewer.page.getByRole('button', { name: 'Change growth conditions' })).toHaveCount(0)
  expect(await axe(viewer.page, 'main')).toEqual([])
  await viewer.close()
})
