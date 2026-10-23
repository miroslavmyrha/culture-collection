import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, username, watchCsp } from './support.js'

// Requests for material (#18, part A) against the real API. seed_e2e made two strains that may
// go out (Testella exempli and Mockia vulgaris e2e supply, invented taxa, the second with a
// dual-use restriction so a manager approves it), the requesters E2E Institute of Microbiology
// and E2E Unnotified Laboratory, and a request blocked by a legal gate. The request of the
// first test names the run in its end use; it is cancelled at the end, which frees its vial
// for the next run. The shipment test (#88) enters, approves and ships a request of its own:
// one vial of the supply leaves per run, and seed_e2e tops the supply up. The two-person test
// (#89) takes the regulated request seed_e2e approved as e2e-manager, which it enters again on
// each run. It works as the sessions auth.setup.ts signed in.

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

test('a curator ships an approved request by keyboard and its vial shows as distributed', async ({ browser }) => {
  // Entered, accepted and approved here (Testella exempli e2e supply: no finding needs a
  // manager), so every run ships a request of its own.
  const curator = await as(browser, 'e2e-curator')
  const violations = await watchCsp(curator.page)
  const page = curator.page
  const lab = await labPath(page)
  await page.goto(`${lab}/requests/new`)
  const form = page.getByRole('form', { name: 'New request' })
  await form.getByRole('combobox', { name: 'Requester' }).selectOption({ label: 'E2E Institute of Microbiology (CZ)' })
  await form.getByRole('combobox', { name: 'Use' }).selectOption('teaching')
  await form.getByRole('textbox', { name: 'End use' }).fill(`Shipped in run ${RUN}.`)
  await form.getByRole('combobox', { name: 'Declared containment level' }).selectOption('1')
  // The full name: 'Testella exempli e2e' also finds the regulated strain of the vial tests.
  await form.getByRole('combobox', { name: 'Strain 1' }).fill('Testella exempli e2e supply')
  const choices = page.getByRole('listbox').getByRole('option')
  await expect(choices).toHaveCount(1)
  await choices.click()
  await form.getByRole('button', { name: 'Enter the request' }).click()
  await expect(page.getByRole('heading', { level: 1, name: /^Request \d{4}\/\d+$/ })).toBeVisible()

  await page.getByRole('button', { name: 'Record an acceptance' }).click()
  const acceptance = page.getByRole('dialog', { name: 'Record an acceptance of the MTA' })
  await acceptance.getByRole('textbox', { name: 'Signed by' }).fill('E2E Signatory')
  await acceptance.getByRole('combobox', { name: "Signer's role" }).selectOption('head_of_institution')
  await acceptance.getByRole('checkbox', { name: 'The signer may bind the institution' }).check()
  await acceptance.getByLabel('Signed copy').setInputFiles({ name: 'signed.pdf', mimeType: 'application/pdf', buffer: PDF })
  await acceptance.getByRole('button', { name: 'Record the acceptance' }).click()
  await expect(acceptance).toBeHidden()
  await page.getByRole('button', { name: 'Approve and reserve the vials' }).click()
  const approve = page.getByRole('dialog', { name: /^Approve request/ })
  await approve.getByRole('button', { name: 'Approve and reserve' }).click()
  await expect(approve).toBeHidden()
  const vialCell = page.getByRole('table', { name: 'Strains' }).getByRole('row').nth(1).getByRole('cell').nth(4)
  await expect(vialCell).toHaveText(/^\S+ \d+ \/ \d+ \/ \d+$/)
  const label = (await vialCell.textContent()) ?? ''

  // The dialog by keyboard: it opens on the transport class, Tab walks the fields in order.
  const ship = page.getByRole('button', { name: 'Ship the vials' })
  await ship.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: /^Ship request/ })
  const transport = dialog.getByRole('combobox', { name: 'Transport class' })
  await expect(transport).toBeFocused()
  expect(await axe(page, '[role="dialog"]')).toEqual([])
  await transport.selectOption('un3373')
  await expect(dialog.getByRole('combobox', { name: 'Packing' })).toHaveValue('p650')
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('combobox', { name: 'Basis of the classification' })).toBeFocused()
  await dialog.getByRole('combobox', { name: 'Basis of the classification' }).selectOption('indicative_list')
  await dialog.getByRole('textbox', { name: 'Responsible person', exact: true }).focus()
  await page.keyboard.type('E2E Responsible')
  await page.keyboard.press('Tab')
  await page.keyboard.type('+420 555 000 111')
  await page.keyboard.press('Tab')
  await page.keyboard.type('E2E Courier')
  await page.keyboard.press('Tab')
  await page.keyboard.type(`E2E${RUN}`)
  await dialog.getByRole('button', { name: 'Ship', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(dialog).toBeHidden()
  await expect(page.getByText(/Shipped by e2e-curator on /)).toBeVisible()
  const shipment = page.getByRole('region', { name: 'Shipment' })
  await expect(shipment).toContainText('UN 3373, Biological substance, Category B')
  await expect(shipment).toContainText('E2E Responsible, +420 555 000 111')
  await expect(page.getByRole('table', { name: 'Strains' }).getByRole('columnheader', { name: 'Shipped vials' })).toBeVisible()
  await expect(vialCell).toHaveText(label)
  await expect(page.getByRole('button', { name: 'Cancel the request' })).toHaveCount(0)
  const requestUrl = page.url()

  // The delivery note was written with the shipment (#90): opened from the list, printable,
  // its text as stored, naming the vial, the class and the person who answers for it.
  const documents = page.getByRole('list', { name: 'Documents of the shipment' })
  await expect(documents.getByRole('listitem')).toHaveCount(1)
  await documents.getByRole('link', { name: 'View and print: Delivery note' }).click()
  await expect(page.getByRole('heading', { level: 1, name: /^Delivery note, request \d{4}\/\d+$/ })).toBeVisible()
  const text = page.getByLabel('Document text')
  await expect(text).toContainText(`     ${label}`)
  await expect(text).toContainText('Transport class: UN 3373, Biological substance, Category B')
  await expect(text).toContainText('Responsible person: E2E Responsible, +420 555 000 111')
  await expect(page.getByRole('button', { name: 'Print' })).toBeVisible()
  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Download as text' }).click()
  expect((await download).suggestedFilename()).toMatch(/^delivery_note-[0-9a-f-]{36}\.txt$/)
  // On paper only the document shows: the bar and the controls are not printed.
  await page.emulateMedia({ media: 'print' })
  await expect(page.getByRole('banner')).toBeHidden()
  await expect(page.getByRole('button', { name: 'Print' })).toBeHidden()
  await expect(text).toBeVisible()
  await page.emulateMedia({ media: 'screen' })
  expect(await axe(page, 'main')).toEqual([])
  await page.goto(requestUrl)

  // The strain page lists the vial as distributed, with no place.
  const accession = label.split(' / ')[0] ?? ''
  await page.goto(`${lab}/strains?search=${encodeURIComponent(accession)}`)
  await page.getByRole('link', { name: accession, exact: true }).click()
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  await expect(page.getByRole('table', { name: 'Vials' }).getByRole('row', { name: new RegExp(`^${escaped} Distributed Left the collection`) })).toBeVisible()
  expect(violations()).toEqual([])
  await curator.close()

  // A viewer at 320 px reads the shipment, without the person who answers for it.
  const viewer = await as(browser, 'e2e-viewer', 320)
  await viewer.page.goto(requestUrl)
  const seen = viewer.page.getByRole('region', { name: 'Shipment' })
  await expect(seen).toContainText('E2E Courier')
  await expect(seen).not.toContainText('E2E Responsible')
  // It sees that the delivery note exists, and opens none: it names a person.
  const listed = viewer.page.getByRole('list', { name: 'Documents of the shipment' })
  await expect(listed).toContainText('Delivery note, SHA-256')
  await expect(listed.getByRole('link')).toHaveCount(0)
  expect(await viewer.page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
  expect(await axe(viewer.page, 'main')).toEqual([])
  await viewer.close()
})

test('a curator prepares a regulated shipment, and a manager who did not approve it confirms it', async ({ browser }) => {
  // Approved by e2e-manager in seed_e2e, found by its end use among the approved requests.
  const curator = await as(browser, 'e2e-curator', 320)
  const violations = await watchCsp(curator.page)
  const page = curator.page
  const lab = await labPath(page)
  const id = await page.evaluate(async (path) => {
    const list: unknown = await (await fetch(`/api/v1${path}/requests/?status=approved&limit=200`)).json()
    const rows: unknown = typeof list === 'object' && list !== null ? Reflect.get(list, 'results') : []
    for (const row of Array.isArray(rows) ? rows : []) {
      const rowId: unknown = Reflect.get(row, 'public_id')
      const detail: unknown = await (await fetch(`/api/v1${path}/requests/${String(rowId)}/`)).json()
      if (typeof detail === 'object' && detail !== null && Reflect.get(detail, 'end_use') === 'E2E seed: research on a dual-use strain, approved and ready to prepare.') return String(rowId)
    }
    return ''
  }, lab)
  expect(id, 'seed_e2e made an approved regulated request').not.toBe('')
  const requestUrl = `${lab}/requests/${id}`
  await page.goto(requestUrl)
  await expect(page.getByText(/leaves in two steps/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Ship the vials' })).toHaveCount(0)
  const vialCell = page.getByRole('table', { name: 'Strains' }).getByRole('row').nth(1).getByRole('cell').nth(4)
  const label = (await vialCell.textContent()) ?? ''
  expect(label).toMatch(/^\S+ \d+ \/ \d+ \/ \d+$/)

  // Prepared by keyboard at 320 px: the dialog opens on the transport class.
  await page.getByRole('button', { name: 'Prepare the shipment' }).focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: /^Prepare the shipment of request/ })
  await expect(dialog.getByRole('combobox', { name: 'Transport class' })).toBeFocused()
  expect(await axe(page, '[role="dialog"]')).toEqual([])
  await page.keyboard.press('Tab')
  await dialog.getByRole('combobox', { name: 'Basis of the classification' }).selectOption('exempt_non_pathogenic')
  await dialog.getByRole('textbox', { name: 'Responsible person', exact: true }).focus()
  await page.keyboard.type('E2E Responsible')
  await page.keyboard.press('Tab')
  await page.keyboard.type('+420 555 000 222')
  await page.keyboard.press('Tab')
  await page.keyboard.type('E2E Courier')
  await dialog.getByRole('button', { name: 'Prepare', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(dialog).toBeHidden()
  await expect(page.getByText(/The shipment was prepared by e2e-curator on .* and waits for a second person/)).toBeVisible()
  await expect(page.getByText('You prepared this shipment, so a different person confirms it.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Confirm the shipment' })).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Prepared shipment' })).toContainText('E2E Courier')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
  expect(await axe(page, 'main')).toEqual([])
  // The server refuses the preparer too, for the very preparation shown.
  const preparation = await page.evaluate(async (url) => {
    const body: unknown = await (await fetch(`/api/v1${url}/`)).json()
    const list: unknown = typeof body === 'object' && body !== null ? Reflect.get(body, 'preparations') : []
    const first: unknown = Array.isArray(list) ? list[0] : undefined
    return typeof first === 'object' && first !== null ? String(Reflect.get(first, 'public_id')) : ''
  }, requestUrl)
  const own = await post(page, `/api/v1${requestUrl}/confirm-shipment/`, { preparation })
  expect(own.status).toBe(403)
  expect(own.body).toContain('confirm_own_preparation')
  expect(violations()).toEqual([])
  await curator.close()

  // The e2e user, a manager who did not approve it, confirms what was prepared.
  const manager = await as(browser, username)
  const mpage = manager.page
  await mpage.goto(requestUrl)
  await mpage.getByRole('button', { name: 'Confirm the shipment' }).click()
  const confirm = mpage.getByRole('alertdialog', { name: /^Confirm the shipment of request/ })
  await expect(confirm.getByRole('button', { name: 'Cancel', exact: true })).toBeFocused()
  await expect(confirm).toContainText('E2E Courier')
  expect(await axe(mpage, '[role="alertdialog"]')).toEqual([])
  await confirm.getByRole('button', { name: 'Confirm and ship' }).click()
  await expect(confirm).toBeHidden()
  await expect(mpage.getByText(new RegExp(`Prepared by e2e-curator on .*, confirmed and shipped by ${username} on `))).toBeVisible()
  await expect(mpage.getByRole('region', { name: 'Shipment' })).toContainText('Confirmed by')
  await expect(mpage.getByRole('table', { name: 'Strains' }).getByRole('columnheader', { name: 'Shipped vials' })).toBeVisible()

  // The strain page lists the vial as distributed, with no place.
  const accession = label.split(' / ')[0] ?? ''
  await mpage.goto(`${lab}/strains?search=${encodeURIComponent(accession)}`)
  await mpage.getByRole('link', { name: accession, exact: true }).click()
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  await expect(mpage.getByRole('table', { name: 'Vials' }).getByRole('row', { name: new RegExp(`^${escaped} Distributed Left the collection`) })).toBeVisible()
  await manager.close()
})
