import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, username, watchCsp } from './support.js'

// The depositor's answer (#144, walkthrough C9) against the real API: commercial research that
// the depositor's terms leave on request. Each test makes a strain of its own through the API
// with e2e-curator's session (a deposit whose terms name MTA STD and leave commercial research on
// request, accepted, one distribution batch of two vials, checked and released), enters a
// request of E2E Institute of Microbiology for one vial and records the MTA acceptance. Strains
// are never deleted, so the names carry the run. The approved request is cancelled at the end.

test.describe.configure({ timeout: 120_000 })

const RUN = Date.now().toString(36)
const PDF = Buffer.from('%PDF-1.4\n% an invented answer of a depositor, e2e run\n%%EOF\n')

async function as(browser: Browser, name: string) {
  const context = await browser.newContext({ storageState: signedInAs(name), viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

/** A strain of this run whose terms leave commercial research on request, and a request for it with the MTA accepted. Answers the request's page. */
async function commercialRequest(page: Page, name: string): Promise<string> {
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeVisible()
  return page.evaluate(
    async ({ strainName, pdf }) => {
      await fetch('/api/v1/auth/csrf/')
      const token = decodeURIComponent(/(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? '')
      const lab = location.pathname.split('/')[2] ?? ''
      const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': token }
      type Made = { public_id: string; strain?: { public_id: string } | null }
      const send = async (path: string, body: unknown): Promise<Made> => {
        const response = await fetch(`/api/v1/labs/${lab}/${path}`, { method: 'POST', headers, body: JSON.stringify(body) })
        if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`)
        const made: Made = await response.json()
        return made
      }
      const read = async <T>(url: string): Promise<T> => {
        const body: T = await (await fetch(url.startsWith('/') ? url : `/api/v1/labs/${lab}/${url}`, { headers })).json()
        return body
      }
      type Listing<T> = { results: T[] }
      const today = new Date().toLocaleDateString('sv')
      const depositor = (await read<Listing<{ public_id: string }>>('depositors/?search=E2E')).results[0]?.public_id
      const mta = (await read<Listing<{ public_id: string; code: string; version: number }>>('mta-templates/')).results
        .filter((t) => t.code === 'STD')
        .toSorted((a, b) => b.version - a.version)[0]
      const uses = ['research_noncommercial', 'research_commercial', 'teaching', 'diagnostics', 'production', 'reference_qc', 'patent_deposit_related', 'redistribution']
      const deposit = await send('deposits/', {
        depositor,
        received_on: today,
        condition: 'intact',
        name_as_received: strainName,
        terms: { mta: mta?.public_id, abs_scope: 'not_in_scope', country_of_origin: 'CZ', uses: uses.map((use) => ({ use, decision: use === 'research_commercial' ? 'on_request' : 'permit' })) },
      })
      await send(`deposits/${deposit.public_id}/start-check/`, {})
      const taxa = await read<Listing<{ public_id: string; name: string }>>('/api/v1/taxa/?search=exempli')
      const accepted = await send(`deposits/${deposit.public_id}/accept/`, {
        taxon: taxa.results.find((t) => t.name === 'Testella exempli')?.public_id,
        identified_on: today,
        identification_method: 'MALDI-TOF MS',
        risk_group: 1,
        country_of_origin: 'CZ',
        restrictions: [],
      })
      const strain = accepted.strain?.public_id ?? ''
      const passage = (await read<Listing<{ public_id: string }>>(`passages/?strain=${strain}`)).results[0]?.public_id
      const batch = await send('batches/', { passage, method: 'cryo_minus80', purpose: 'distribution', cryoprotectant: '10 % glycerol', preserved_on: today, vial_count: 2 })
      const vial = (await read<Listing<{ public_id: string }>>(`vials/?batch=${batch.public_id}`)).results[0]?.public_id
      for (const [kind, method] of [['identity', 'sequencing'], ['purity', 'streak_plate'], ['viability', 'growth']]) {
        await send('batch-checks/', { batch: batch.public_id, kind, stage: 'after_preservation', checked_on: today, method, result: 'pass', vial })
      }
      await send(`batches/${batch.public_id}/release/`, { reason: 'Identity, purity and viability passed.' })
      const requester = (await read<Listing<{ public_id: string }>>('requesters/?search=E2E%20Institute')).results[0]?.public_id
      const request = await send('requests/', { requester, use: 'research_commercial', end_use: `Enzyme screening for a company, ${strainName}.`, containment_level: 2, lines: [{ strain, quantity: 1 }] })
      const signed = new FormData()
      for (const [k, v] of Object.entries({ mta: mta?.public_id ?? '', signer_name: 'E2E Signatory', signer_role: 'head_of_institution', authorised_signatory: 'true', accepted_on: today })) signed.append(k, v)
      signed.append('file', new Blob([pdf], { type: 'application/pdf' }), 'signed.pdf')
      const acceptance = await fetch(`/api/v1/labs/${lab}/requests/${request.public_id}/acceptances/`, { method: 'POST', headers: { 'X-CSRFToken': token }, body: signed })
      if (!acceptance.ok) throw new Error(`acceptance: ${acceptance.status} ${await acceptance.text()}`)
      return `/labs/${lab}/requests/${request.public_id}`
    },
    { strainName: name, pdf: PDF.toString('latin1') },
  )
}

/** An approval through the API, as a script or a stale page would send it. */
async function approveByApi(page: Page, path: string) {
  return page.evaluate(async (target) => {
    await fetch('/api/v1/auth/csrf/')
    const token = decodeURIComponent(/(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? '')
    const response = await fetch(target, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token }, body: JSON.stringify({ reason: 'The depositor agreed by phone.' }) })
    return { status: response.status, body: await response.text() }
  }, `/api/v1${path}/approve/`)
}

test('a curator records the depositor’s yes with the letter, and the manager approves', async ({ browser }) => {
  const curator = await as(browser, 'e2e-curator')
  const violations = await watchCsp(curator.page)
  const path = await commercialRequest(curator.page, `Testella exempli yes ${RUN}`)
  await curator.page.goto(path)
  await expect(curator.page.getByRole('list', { name: 'Blocks the approval' })).toContainText('only on request to the depositor, and no answer of the depositor is recorded')
  await expect(curator.page.getByRole('list', { name: 'Depositor’s answers' })).toContainText('No answer is recorded yet.')

  await curator.page.getByRole('button', { name: 'Record the depositor’s yes' }).click()
  const dialog = curator.page.getByRole('dialog', { name: 'Record the depositor’s yes' })
  expect(await axe(curator.page, '[role="dialog"]')).toEqual([])
  await dialog.getByRole('textbox', { name: 'Note' }).fill('The depositor agreed by e-mail to screening for one company.')
  await dialog.getByLabel('Depositor’s letter or e-mail').setInputFiles({ name: 'answer.pdf', mimeType: 'application/pdf', buffer: PDF })
  await dialog.getByRole('button', { name: 'Record the yes' }).click()
  await expect(dialog).toBeHidden()
  const answers = curator.page.getByRole('list', { name: 'Depositor’s answers' })
  await expect(answers).toContainText(/the depositor agreed to commercial research \(answer of \d{4}-\d{2}-\d{2}, recorded by e2e-curator on .*\): The depositor agreed by e-mail/)
  // The letter comes back as it was sent.
  const download = curator.page.waitForEvent('download')
  await answers.getByRole('link', { name: /^Download the depositor’s answer for / }).click()
  const file = await (await download).path()
  expect(file).toBeTruthy()
  await expect(curator.page.getByText('Nothing stands in the way: a curator may approve it.')).toBeVisible()
  await expect(curator.page.getByRole('button', { name: /^Record the depositor’s / })).toHaveCount(0)

  const manager = await as(browser, username)
  await manager.page.goto(path)
  await manager.page.getByRole('button', { name: 'Approve and reserve the vials' }).click()
  const approve = manager.page.getByRole('dialog', { name: /^Approve request/ })
  await approve.getByRole('button', { name: 'Approve and reserve' }).click()
  await expect(approve).toBeHidden()
  await expect(manager.page.getByText(new RegExp(`^Approved by ${username} on `))).toBeVisible()

  // Cancelled, so no approved request of this run stays behind.
  await curator.page.goto(path)
  await curator.page.getByRole('button', { name: 'Cancel the request' }).click()
  const cancel = curator.page.getByRole('alertdialog', { name: /^Cancel request/ })
  await cancel.getByRole('textbox', { name: 'Reason' }).fill(`End of e2e run ${RUN}.`)
  await cancel.getByRole('button', { name: 'Cancel the request' }).click()
  await expect(curator.page.getByText(/^Cancelled by e2e-curator on /)).toBeVisible()
  expect(violations()).toEqual([])
  await curator.close()
  await manager.close()
})

test('without a yes the manager’s approval is refused, and the depositor’s no rejects the request with the answer as the reason', async ({ browser }) => {
  const curator = await as(browser, 'e2e-curator')
  const path = await commercialRequest(curator.page, `Testella exempli no ${RUN}`)

  const manager = await as(browser, username)
  await manager.page.goto(path)
  await expect(manager.page.getByRole('list', { name: 'Blocks the approval' })).toContainText('only on request to the depositor')
  await expect(manager.page.getByRole('button', { name: 'Approve and reserve the vials' })).toHaveCount(0)
  const refused = await approveByApi(manager.page, path)
  expect(refused.status).toBe(422)
  expect(JSON.parse(refused.body)).toMatchObject({ code: 'request_blocked' })

  await curator.page.goto(path)
  await curator.page.getByRole('button', { name: 'Record the depositor’s no' }).click()
  const dialog = curator.page.getByRole('alertdialog', { name: /^Record the depositor’s no and reject request \d{4}\/\d+\?$/ })
  await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeFocused()
  await dialog.getByRole('textbox', { name: 'Note' }).fill('The depositor keeps commercial use for its own company.')
  await dialog.getByRole('button', { name: 'Record the no and reject' }).click()
  await expect(dialog).toBeHidden()
  await expect(curator.page.getByText(/^Status: Rejected\.$/)).toBeVisible()
  await expect(curator.page.getByText(/^Rejected by e2e-curator on .*: The depositor declined commercial research of \S+ \d+ \(answer of \d{4}-\d{2}-\d{2}\): The depositor keeps commercial use for its own company\.$/)).toBeVisible()
  await curator.close()
  await manager.close()
})
