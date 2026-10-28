import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, username, watchCsp } from './support.js'

// The reveal log (#83) against the real API. seed_e2e has a regulated strain (Testella exempli
// e2e regulated) with two vials in E2E freezer > Rack 1 > Box R. The e2e user, the lab's manager,
// gives e2e-technician the location grant, the technician reveals the first vial through the API,
// and the manager revokes the grant again, so the technician holds none afterwards. Not
// e2e-curator: vials.spec.ts checks that the curator holds no grant, and may run at the same time.
// Then the manager reads the reveal in the log, and a viewer gets no tab.

test.describe.configure({ timeout: 120_000 })

const REGULATED = 'Testella exempli e2e regulated'
const TECHNICIAN = 'e2e-technician'

async function as(browser: Browser, user: string) {
  const context = await browser.newContext({ storageState: signedInAs(user), viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

/** A JSON read or write with the session and its CSRF token, from the page's origin; fails loudly. */
async function call<T>(page: Page, verb: 'GET' | 'POST', url: string, payload?: unknown): Promise<T> {
  const answer: T = await page.evaluate(
    async ({ verb: how, url: where, payload: sent }) => {
      await fetch('/api/v1/auth/csrf/')
      const token = decodeURIComponent(/(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? '')
      const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': token }
      const response = how === 'GET' ? await fetch(where, { headers }) : await fetch(where, { method: 'POST', headers, body: JSON.stringify(sent ?? {}) })
      if (!response.ok) throw new Error(`${how} ${where}: ${response.status} ${await response.text()}`)
      return response.status === 204 ? null : response.json()
    },
    { verb, url, payload },
  )
  return answer
}

test("a manager reads who revealed a regulated vial's place, without the place; a viewer has no tab", async ({ browser }) => {
  const manager = await as(browser, username)
  const page = manager.page
  const violations = await watchCsp(page)
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeVisible()
  const labUrl = page.url()
  const lab = new URL(labUrl).pathname.split('/')[2] ?? ''

  // The grant, the reveal and the revocation, through the API.
  const members = await call<{ results: { public_id: string; username: string }[] }>(page, 'GET', `/api/v1/labs/${lab}/members/?limit=200`)
  const member = members.results.find((m) => m.username === TECHNICIAN)?.public_id
  const grant = await call<{ public_id: string }>(page, 'POST', `/api/v1/labs/${lab}/location-grants/`, { member, reason: 'e2e of the reveal log' })
  let label = ''
  try {
    const technician = await as(browser, TECHNICIAN)
    await technician.page.goto('/labs')
    const strains = await call<{ results: { public_id: string }[] }>(technician.page, 'GET', `/api/v1/labs/${lab}/strains/?search=${encodeURIComponent(REGULATED)}`)
    const strain = strains.results[0]?.public_id ?? ''
    const vials = await call<{ results: { public_id: string; label: string; seq: number }[] }>(technician.page, 'GET', `/api/v1/labs/${lab}/vials/?strain=${strain}`)
    const vial = vials.results.find((v) => v.seq === 1)
    label = vial?.label ?? ''
    await call<unknown>(technician.page, 'POST', `/api/v1/labs/${lab}/vials/${vial?.public_id ?? ''}/reveal-location/`)
    await technician.close()
  } finally {
    await call<unknown>(page, 'POST', `/api/v1/labs/${lab}/location-grants/${grant.public_id}/revoke/`, { reason: 'e2e of the reveal log done' })
  }
  expect(label).toMatch(/ \/ 1$/)

  await page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Reveals', exact: true }).click()
  const heading = page.getByRole('heading', { level: 1, name: 'Reveals of E2E lab' })
  await expect(heading).toBeFocused()
  await expect(page).toHaveTitle('Reveals of E2E lab | Culture collection')

  await page.getByRole('button', { name: 'This month' }).click()
  await expect(page).toHaveURL(/since=\d{4}-\d{2}-01&until=\d{4}-\d{2}-\d{2}/)
  const table = page.getByRole('table', { name: 'Reveals', exact: true })
  // Newest first: this run's reveal is the technician's first row.
  const row = table.getByRole('row', { name: new RegExp(TECHNICIAN) }).first()
  await expect(row).toContainText(label)
  await row.getByRole('button', { name: `Only the reveals of ${TECHNICIAN}` }).click()
  await expect(page).toHaveURL(/person=/)
  await expect(page.getByText(`The reveals of ${TECHNICIAN}.`)).toBeVisible()
  await expect(table.getByRole('row').nth(1)).toContainText(label)
  // The place of the vial is nowhere on the page.
  const main = page.getByRole('main')
  await expect(main).not.toContainText('Box R')
  await expect(main).not.toContainText('E2E freezer')
  expect(await axe(page, 'main')).toEqual([])
  expect(violations()).toEqual([])
  await manager.close()

  const viewer = await as(browser, 'e2e-viewer')
  await viewer.page.goto(labUrl)
  const tabs = viewer.page.getByRole('navigation', { name: 'Lab sections' })
  await expect(tabs.getByRole('link', { name: 'Strains', exact: true })).toBeVisible()
  await expect(tabs.getByRole('link', { name: 'Reveals', exact: true })).toHaveCount(0)
  await viewer.page.goto(`${labUrl}/reveals`)
  await expect(viewer.page.getByText('Only managers see who revealed regulated locations.')).toBeVisible()
  await expect(viewer.page.getByRole('table')).toHaveCount(0)
  await viewer.close()
})
