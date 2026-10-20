import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, username, watchCsp } from './support.js'

// Requests for material (#18, part A) against the real API. seed_e2e made two strains that may
// go out (Testella exempli and Mockia vulgaris e2e supply, invented taxa, the second with a
// dual-use restriction so a manager approves it), the requesters E2E Institute of Microbiology
// and E2E Unnotified Laboratory, and a request blocked by a legal gate. The request of the
// first test names the run in its end use; it is cancelled at the end, which frees its vial
// for the next run. It works as the sessions auth.setup.ts signed in.

const RUN = Date.now().toString(36)
const PDF = Buffer.from('%PDF-1.4\n% an invented signed copy of an e2e run\n%%EOF\n')

async function as(browser: Browser, name: string, width = 1280) {
  const context = await browser.newContext({ storageState: signedInAs(name), viewport: { width, height: width === 320 ? 640 : 900 } })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

async function labPath(page: Page) {
  await page.goto('/labs')
  const href = await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).getAttribute('href')
  return href ?? ''
}

/** A call to the API from the page, with the session and its CSRF token. */
async function post(page: Page, url: string, body: Record<string, unknown>) {
  return page.evaluate(
    async ([target, payload]) => {
      await fetch('/api/v1/auth/csrf/')
      const token = /(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? ''
      const response = await fetch(target, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(token) },
        body: JSON.stringify(payload),
      })
      return { status: response.status, body: await response.text() }
    },
    [url, body] as const,
  )
}

test('a curator enters a request with the signed MTA and a manager approves it, which reserves a vial', async ({ browser }) => {
  const curator = await as(browser, 'e2e-curator')
  const violations = await watchCsp(curator.page)
  const lab = await labPath(curator.page)
  await curator.page.goto(`${lab}/requests/new`)
  const form = curator.page.getByRole('form', { name: 'New request' })
  await form.getByRole('combobox', { name: 'Requester' }).selectOption({ label: 'E2E Institute of Microbiology (CZ)' })
  await form.getByRole('combobox', { name: 'Use' }).selectOption('research_noncommercial')
  await form.getByRole('textbox', { name: 'End use' }).fill(`Growth curves of run ${RUN}.`)
  await form.getByRole('combobox', { name: 'Declared containment level' }).selectOption('2')
  const strain = form.getByRole('combobox', { name: 'Strain 1' })
  await strain.fill('Mockia vulgaris e2e')
  await curator.page.getByRole('option', { name: /Mockia vulgaris/ }).first().click()
  await form.getByRole('button', { name: 'Enter the request' }).click()

  await expect(curator.page.getByRole('heading', { level: 1, name: /^Request \d{4}\/\d+$/ })).toBeVisible()
  const requestUrl = curator.page.url()
  await expect(curator.page.getByRole('list', { name: 'Blocks the approval' })).toContainText('no acceptance of MTA STD version 1')
  await expect(curator.page.getByRole('list', { name: 'Needs a manager’s approval' })).toContainText('is regulated (dual_use): a manager approves it.')

  await curator.page.getByRole('button', { name: 'Record an acceptance' }).click()
  const dialog = curator.page.getByRole('dialog', { name: 'Record an acceptance of the MTA' })
  await dialog.getByRole('textbox', { name: 'Signed by' }).fill('E2E Signatory')
  await dialog.getByRole('combobox', { name: "Signer's role" }).selectOption('head_of_institution')
  await dialog.getByRole('checkbox', { name: 'The signer may bind the institution' }).check()
  await dialog.getByLabel('Signed copy').setInputFiles({ name: 'signed.pdf', mimeType: 'application/pdf', buffer: PDF })
  await dialog.getByRole('button', { name: 'Record the acceptance' }).click()
  await expect(dialog).toBeHidden()
  await expect(curator.page.getByText(/MTA STD version 1, accepted on .* by E2E Signatory/)).toBeVisible()
  await expect(curator.page.getByRole('list', { name: 'Blocks the approval' })).toBeHidden()
  // A curator may not approve over a manager's finding: the button is not offered.
  await expect(curator.page.getByText('A manager approves this request.')).toBeVisible()
  await expect(curator.page.getByRole('button', { name: 'Approve and reserve the vials' })).toHaveCount(0)

  const manager = await as(browser, username)
  await manager.page.goto(requestUrl)
  await manager.page.getByRole('button', { name: 'Approve and reserve the vials' }).click()
  const approve = manager.page.getByRole('dialog', { name: /^Approve request/ })
  expect(await axe(manager.page, '[role="dialog"]')).toEqual([])
  await approve.getByRole('textbox', { name: 'Reason' }).fill('Dual-use inside the EU: no licence needed.')
  await approve.getByRole('button', { name: 'Approve and reserve' }).click()
  await expect(approve).toBeHidden()
  await expect(manager.page.getByText(new RegExp(`Approved by ${username} on .*: Dual-use inside the EU`))).toBeVisible()
  const reservedCell = manager.page.getByRole('table', { name: 'Strains' }).getByRole('row').nth(1).getByRole('cell').nth(4)
  await expect(reservedCell).toHaveText(/^\S+ \d+ \/ \d+ \/ \d+$/)

  // The curator cancels it, so the vial is free again for the next run.
  await curator.page.goto(requestUrl)
  await curator.page.getByRole('button', { name: 'Cancel the request' }).click()
  const cancel = curator.page.getByRole('alertdialog', { name: /^Cancel request/ })
  await expect(cancel.getByRole('button', { name: 'Cancel', exact: true })).toBeFocused()
  await cancel.getByRole('textbox', { name: 'Reason' }).fill(`End of e2e run ${RUN}.`)
  await cancel.getByRole('button', { name: 'Cancel the request' }).click()
  await expect(curator.page.getByText(/^Cancelled by e2e-curator on /)).toBeVisible()
  // The vial is free again: the line lists none reserved.
  await expect(curator.page.getByRole('table', { name: 'Strains' }).getByRole('row').nth(1).getByRole('cell').nth(4)).toHaveText('None')
  expect(violations()).toEqual([])
  await curator.close()
  await manager.close()
})

test('a request blocked by a legal gate is not approved, on screen or through the API', async ({ browser }) => {
  const curator = await as(browser, 'e2e-curator')
  const lab = await labPath(curator.page)
  await curator.page.goto(`${lab}/requests?search=Unnotified`)
  const link = curator.page.getByRole('table', { name: 'Requests' }).getByRole('link').first()
  await link.click()
  const blocks = curator.page.getByRole('list', { name: 'Blocks the approval' })
  await expect(blocks).toContainText('the requester shows no reference of its notice to SÚJB (§ 17a)')
  await expect(curator.page.getByRole('button', { name: 'Approve and reserve the vials' })).toHaveCount(0)
  const answer = await post(curator.page, `/api/v1${curator.page.url().replace(/^https?:\/\/[^/]+/, '').replace(/\/$/, '')}/approve/`, { reason: 'try anyway' })
  expect(answer.status).toBe(422)
  expect(answer.body).toContain('request_blocked')
  await curator.close()
})

test('a viewer reads the requests and what is reserved, at 320 px, and the API refuses its writes', async ({ browser }) => {
  const viewer = await as(browser, 'e2e-viewer', 320)
  const lab = await labPath(viewer.page)
  await viewer.page.goto(`${lab}/requests`)
  await expect(viewer.page.getByRole('heading', { level: 1, name: 'Requests of E2E lab' })).toBeVisible()
  await expect(viewer.page.getByRole('link', { name: 'Enter a request' })).toHaveCount(0)
  expect(await viewer.page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
  expect(await axe(viewer.page, 'main')).toEqual([])
  await viewer.page.getByRole('table', { name: 'Requests' }).getByRole('link').first().click()
  await expect(viewer.page.getByRole('heading', { level: 1, name: /^Request / })).toBeVisible()
  await expect(viewer.page.getByRole('heading', { level: 2, name: 'Strains' })).toBeVisible()
  expect(await viewer.page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
  expect(await axe(viewer.page, 'main')).toEqual([])
  await expect(viewer.page.getByRole('main').getByRole('button')).toHaveCount(0)
  const requestPath = viewer.page.url().replace(/^https?:\/\/[^/]+/, '').replace(/\/$/, '')
  for (const action of ['approve', 'reject', 'cancel']) {
    const answer = await post(viewer.page, `/api/v1${requestPath}/${action}/`, { reason: 'not mine to decide' })
    expect(answer.status, action).toBe(403)
  }
  const requesters = await viewer.page.evaluate(async (path) => (await fetch(`/api/v1${path}/requesters/`)).status, lab)
  expect(requesters).toBe(403)
  await viewer.close()
})
