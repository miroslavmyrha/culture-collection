import { expect, test } from '@playwright/test'
import { riskGroupBasis, signedInAs, username, watchCsp } from './support.js'

// #159, act 281/2002 Sb., § 5(5): a manager marks a vial of a RAT strain lost, is told of the duty
// to report the loss to the police, finds the loss on Home and records the report there. The
// strain, its box and its two vials are this run's own, made through the API with e2e-user's
// session (the lab's manager): strains are never deleted, so the spec finds its own by a
// run-unique name. Testella exempli is invented; its RAT restriction here is an invented example.

const RUN = Date.now().toString(36)
const NAME = `Testella exempli lost ${RUN}`

test('a manager is told to report a lost RAT vial to the police, and records the report from Home', async ({ browser }) => {
  const context = await browser.newContext({ storageState: signedInAs(username) })
  const page = await context.newPage()
  const violations = await watchCsp(page)
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeVisible()

  const made = await page.evaluate(
    async ({ run, name }) => {
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
      const today = new Date().toLocaleDateString('sv')
      const depositors = await read<{ results: { public_id: string }[] }>(`/api/v1/labs/${lab}/depositors/?search=E2E`)
      const uses = ['research_noncommercial', 'research_commercial', 'teaching', 'diagnostics', 'production', 'reference_qc', 'patent_deposit_related', 'redistribution']
      const deposit = await send('deposits/', {
        depositor: depositors.results[0]?.public_id,
        received_on: today,
        condition: 'intact',
        name_as_received: name,
        terms: { mta: null, abs_scope: 'unknown', uses: uses.map((use) => ({ use, decision: 'on_request' })) },
      })
      await send(`deposits/${deposit.public_id}/start-check/`, {})
      const taxa = await read<{ results: { public_id: string; name: string }[] }>('/api/v1/taxa/?search=exempli')
      const accepted = await send(`deposits/${deposit.public_id}/accept/`, {
        taxon: taxa.results.find((t) => t.name === 'Testella exempli')?.public_id,
        identified_on: today,
        identification_method: 'MALDI-TOF MS',
        risk_group: 1,
        risk_group_basis: riskGroupBasis,
        animal_pathogenicity: 'unknown',
        plant_pathogenicity: 'unknown',
        isolation_source: '',
        country_of_origin: '',
        isolation_date: '',
        restrictions: [{ kind: 'cz_rat', reference: 'Příloha 2 (invented example)', act: '' }],
      })
      const strain = accepted.strain?.public_id ?? ''
      const freezer = await send('storage-units/', { kind: 'freezer', name: `Freezer l${run}`, max_risk_group: 2 })
      const rack = await send('storage-units/', { kind: 'rack', name: 'Rack 1', parent: freezer.public_id })
      const types = await read<{ results: { public_id: string; name: string }[] }>('/api/v1/box-types/')
      const box = await send('storage-units/', { kind: 'box', name: 'Box 1', parent: rack.public_id, box_type: types.results.find((t) => t.name === '81-place cryobox (9 x 9)')?.public_id })
      const passages = await read<{ results: { public_id: string }[] }>(`/api/v1/labs/${lab}/passages/?strain=${strain}`)
      await send('batches/', {
        passage: passages.results[0]?.public_id,
        method: 'cryo_minus80',
        purpose: 'seed',
        cryoprotectant: '10 % glycerol',
        preserved_on: today,
        vial_count: 2,
        box: box.public_id,
      })
      return { lab, strain, number: accepted.strain?.accession_number ?? '' }
    },
    { run: RUN, name: NAME },
  )
  const label = `${made.number} / 1 / 1`

  // The state dialog names the duty with the section once Lost is chosen, before saving.
  await page.goto(`/labs/${made.lab}/strains/${made.strain}/material`)
  await page.getByRole('button', { name: `Actions for vial ${label}` }).click()
  await page.getByRole('menuitem', { name: 'Change state' }).click()
  const change = page.getByRole('dialog', { name: `Change the state of vial ${label}` })
  const state = change.getByRole('combobox', { name: 'New state' })
  await expect(change.getByText(/281\/2002/)).toHaveCount(0)
  await state.selectOption({ label: 'Lost' })
  await expect(state).toHaveAccessibleDescription(/Police of the Czech Republic without undue delay \(Act 281\/2002 Sb\., § 5\(5\)\)/)
  await change.getByRole('textbox', { name: 'Reason' }).fill('Not in its position at the inventory.')
  await change.getByRole('button', { name: 'Save state' }).click()
  await expect(change).toBeHidden()
  const vials = page.getByRole('table', { name: 'Vials' })
  await expect(vials.getByRole('row', { name: new RegExp(label) })).toContainText('Not reported to the police yet')

  // Home lists the loss for the manager and opens the vial on its strain's Material tab.
  await page.goto('/')
  const losses = page.getByRole('region', { name: /^Losses to report to the police/ })
  await losses.getByRole('link', { name: label, exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/labs/${made.lab}/strains/${made.strain}/material\\?vial=`))
  await expect(vials.getByRole('row')).toHaveCount(2)

  await page.getByRole('button', { name: `Actions for vial ${label}` }).click()
  await page.getByRole('menuitem', { name: 'Record the police report' }).click()
  const record = page.getByRole('dialog', { name: `Record the police report of vial ${label}` })
  await record.getByRole('textbox', { name: 'Police reference' }).fill(`KRPB-${RUN}/TČ-2026 (invented example)`)
  await record.getByRole('textbox', { name: 'Reason' }).fill('Reported at the police station the same day.')
  await record.getByRole('button', { name: 'Record report' }).click()
  await expect(record).toBeHidden()
  await expect(vials.getByRole('row', { name: new RegExp(label) })).toContainText(`reference KRPB-${RUN}/TČ-2026 (invented example)`)

  // Recorded: it waits no more.
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 2, name: /^Waiting for you/ })).toBeVisible()
  await expect(page.getByRole('link', { name: label, exact: true })).toHaveCount(0)
  expect(violations()).toEqual([])
  await context.close()
})
