import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, username, watchCsp } from './support.js'

// The vials to pull for a shipment (#143) against the real API. The curator enters a request of
// this run for two vials of Testella exempli e2e supply and one of Mockia vulgaris e2e supply
// (dual-use, so its place is masked), with the signed MTA; the e2e user, the lab's manager,
// approves it, which reserves the three. The curator builds a freezer of this run with Box 1
// (slot 1) and Box 2 (slot 2), and e2e-technician puts the first supply vial into Box 2 A1, the
// second into Box 1 C3 and the regulated one into Box 1 B1. The technician reads them on the
// request in the order of one walk: Box 1 C3, Box 2 A1, then the regulated vial, hidden and with
// no reveal. The e2e user holds the lab's location grant (seed_e2e) and reveals it there. The
// request is cancelled at the end, which frees the vials for the next run.

test.describe.configure({ timeout: 120_000 })

const RUN = Date.now().toString(36)
const SUPPLY = 'Testella exempli e2e supply'
const REGULATED = 'Mockia vulgaris e2e supply'
type Row = Record<string, unknown>

async function as(browser: Browser, user: string) {
  const context = await browser.newContext({ storageState: signedInAs(user), viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  await page.goto('/')
  return { page, close: () => context.close() }
}

/** A JSON read or write with the session and its CSRF token; a relative path is in the lab. Fails loudly. */
async function api(page: Page, lab: string, path: string, body?: Row): Promise<unknown> {
  const answer = await page.evaluate(
    async ([labId, url, payload]) => {
      await fetch('/api/v1/auth/csrf/')
      const token = decodeURIComponent(/(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? '')
      const target = url.startsWith('/') ? url : `/api/v1/labs/${labId}/${url}`
      const init: RequestInit = { method: payload === undefined ? 'GET' : 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token } }
      if (payload !== undefined) init.body = JSON.stringify(payload)
      const response = await fetch(target, init)
      return { status: response.status, text: await response.text() }
    },
    [lab, path, body] as const,
  )
  if (answer.status >= 400) throw new Error(`${path}: ${answer.status} ${answer.text}`)
  const json: unknown = answer.text === '' ? null : JSON.parse(answer.text)
  return json
}

const isRow = (value: unknown): value is Row => typeof value === 'object' && value !== null && !Array.isArray(value)
/** The rows of a page ({results}) or of a plain list, or of a key of a row. */
const rows = (json: unknown, key = 'results'): Row[] => {
  const value: unknown = isRow(json) ? json[key] : json
  return Array.isArray(value) ? value.filter(isRow) : []
}
const text = (row: unknown, key: string) => {
  const value: unknown = isRow(row) ? row[key] : undefined
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}
const one = (found: Row[], key: string, value: string) => {
  const row = found.find((r) => r[key] === value)
  expect(row, `${key} ${value}`).toBeDefined()
  return row
}

/** The request of this run, entered and accepted by the curator: its id and number. */
async function enterRequest(page: Page, lab: string) {
  const requester = one(rows(await api(page, lab, `requesters/?search=${encodeURIComponent('E2E Institute of Microbiology')}`)), 'institution', 'E2E Institute of Microbiology')
  const strain = async (name: string) => text(one(rows(await api(page, lab, `strains/?search=${encodeURIComponent(name)}`)), 'name_as_received', name), 'public_id')
  const lines = [
    { strain: await strain(SUPPLY), quantity: 2 },
    { strain: await strain(REGULATED), quantity: 1 },
  ]
  const made = await api(page, lab, 'requests/', { requester: text(requester, 'public_id'), use: 'research_noncommercial', end_use: `Pulled in run ${RUN}.`, containment_level: 2, lines })
  const mtaId = text(rows(made, 'lines')[0]?.mta, 'public_id')
  const status = await page.evaluate(
    async ([url, id]) => {
      await fetch('/api/v1/auth/csrf/')
      const token = decodeURIComponent(/(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? '')
      const data = new FormData()
      for (const [k, v] of Object.entries({ mta: id, signer_name: 'E2E Signatory', signer_role: 'head_of_institution', authorised_signatory: 'true', accepted_on: new Date().toLocaleDateString('sv') })) data.append(k, v)
      data.append('file', new Blob(['%PDF-1.4\n% an invented signed copy of an e2e run\n%%EOF\n'], { type: 'application/pdf' }), 'signed.pdf')
      return (await fetch(url, { method: 'POST', headers: { 'X-CSRFToken': token }, body: data })).status
    },
    [`/api/v1/labs/${lab}/requests/${text(made, 'public_id')}/acceptances/`, mtaId] as const,
  )
  expect(status).toBe(201)
  return { id: text(made, 'public_id'), number: text(made, 'number') }
}

/** A freezer of this run with Rack 1 and the named 9 x 9 boxes in it, in slot order. */
async function freezerWithBoxes(page: Page, lab: string, freezer: string, boxes: string[]) {
  const unit = text(await api(page, lab, 'storage-units/', { kind: 'freezer', name: freezer, temperature_c: -80, max_risk_group: 2 }), 'public_id')
  const rack = text(await api(page, lab, 'storage-units/', { kind: 'rack', name: 'Rack 1', parent: unit, slot: 1 }), 'public_id')
  const nine = text(one(rows(await api(page, lab, '/api/v1/box-types/')), 'name', '81-place cryobox (9 x 9)'), 'public_id')
  const ids: string[] = []
  for (const [i, name] of boxes.entries()) ids.push(text(await api(page, lab, 'storage-units/', { kind: 'box', name, parent: rack, slot: i + 1, box_type: nine }), 'public_id'))
  return ids
}

test('a technician reads where the reserved vials lie, in walk order, and a regulated one is revealed only with the grant', async ({ browser }) => {
  const curator = await as(browser, 'e2e-curator')
  const labs = rows(await api(curator.page, '', '/api/v1/labs/?limit=200'))
  const lab = text(one(labs, 'name', 'E2E lab'), 'public_id')
  const request = await enterRequest(curator.page, lab)
  const freezer = `Pull freezer ${RUN}`
  const [box1 = '', box2 = ''] = await freezerWithBoxes(curator.page, lab, freezer, ['Box 1', 'Box 2'])

  const manager = await as(browser, username)
  await api(manager.page, lab, `requests/${request.id}/approve/`, { reason: 'Dual-use inside the EU: no licence needed.' })
  const lines = rows(await api(curator.page, lab, `requests/${request.id}/`), 'lines')
  const reserved = (line: Row | undefined) => rows(line, 'reserved').toSorted((a, b) => text(a, 'label').localeCompare(text(b, 'label'), 'en', { numeric: true }))
  const [first, second] = reserved(lines[0])
  const [masked] = reserved(lines[1])
  expect([first, second, masked].every((v) => v !== undefined)).toBe(true)

  const technician = await as(browser, 'e2e-technician')
  const place = (vial: Row | undefined, box: string, row: number, col: number) => api(technician.page, lab, `vials/${text(vial, 'public_id')}/place/`, { box, row, col })
  await place(first, box2, 1, 1)
  await place(second, box1, 3, 3)
  await place(masked, box1, 2, 1)

  try {
    // The technician opens the approved request and reads the walk.
    const page = technician.page
    const violations = await watchCsp(page)
    await page.goto(`/labs/${lab}/requests/${request.id}`)
    await expect(page).toHaveTitle(`Request ${request.number} | Culture collection`)
    const table = page.getByRole('region', { name: 'Vials to pull' }).getByRole('table', { name: 'Vials to pull' })
    const pulled = table.getByRole('row')
    await expect(pulled).toHaveCount(4)
    await expect(pulled.nth(1)).toHaveText(`1${text(second, 'label')}${freezer} / Rack 1 / Box 1, C3`)
    await expect(pulled.nth(2)).toHaveText(`2${text(first, 'label')}${freezer} / Rack 1 / Box 2, A1`)
    await expect(pulled.nth(3)).toHaveText(`3${text(masked, 'label')}Hidden: regulated strain`)
    await expect(table.getByRole('button', { name: /Reveal/ })).toHaveCount(0)
    expect(await axe(page, 'main')).toEqual([])
    expect(violations()).toEqual([])

    // The e2e user holds the location grant: the regulated vial's place, on request, and hidden again.
    const mpage = manager.page
    await mpage.goto(`/labs/${lab}/requests/${request.id}`)
    const regulatedRow = mpage.getByRole('table', { name: 'Vials to pull' }).getByRole('row').nth(3)
    await expect(regulatedRow).toContainText('Hidden: regulated strain')
    // One button that changes its name: Reveal, then Hide.
    const toggle = regulatedRow.getByRole('button')
    await expect(toggle).toHaveAccessibleName(`Reveal the location of vial ${text(masked, 'label')}`)
    await toggle.click()
    await expect(regulatedRow).toContainText(`${freezer} / Rack 1 / Box 1, B1`)
    await expect(toggle).toHaveAccessibleName(`Hide the location of vial ${text(masked, 'label')}`)
    await expect(toggle).toBeFocused()
    await toggle.click()
    await expect(regulatedRow).toContainText('Hidden: regulated strain')
    await expect(regulatedRow).not.toContainText('Box 1')
  } finally {
    await api(curator.page, lab, `requests/${request.id}/cancel/`, { reason: `e2e run ${RUN} done.` })
    await technician.close()
    await manager.close()
    await curator.close()
  }
})
