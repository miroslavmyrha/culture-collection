import { expect, test } from '@playwright/test'
import { signedInAs, username, watchCsp } from './support.js'

// The destruction of a regulated strain's vial takes two people (#160, ADR 0009): e2e-curator
// marks the vial to destroy and records its destruction on the strain's Material tab, and the e2e
// user, the lab's manager, confirms the record there; only then is the vial destroyed. The
// strain, its box and its vials are this run's own, made through the API with the curator's
// session: strains are never deleted, so the spec finds its own by a run-unique name. Testella
// exempli is invented; its RAT restriction here is an invented example.

const RUN = Date.now().toString(36)
const NAME = `Testella exempli destroyed ${RUN}`

test('a curator records the destruction of a RAT vial and a manager confirms it', async ({ browser }) => {
  const curator = await browser.newContext({ storageState: signedInAs('e2e-curator') })
  const page = await curator.newPage()
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
        animal_pathogenicity: 'unknown',
        plant_pathogenicity: 'unknown',
        isolation_source: '',
        country_of_origin: '',
        isolation_date: '',
        restrictions: [{ kind: 'cz_rat', reference: 'Příloha 2 (invented example)', act: '' }],
      })
      const strain = accepted.strain?.public_id ?? ''
      const freezer = await send('storage-units/', { kind: 'freezer', name: `Freezer d${run}`, max_risk_group: 2 })
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

  // The curator marks the vial to destroy: no state change destroys it, the dialog says where.
  await page.goto(`/labs/${made.lab}/strains/${made.strain}/material`)
  await page.getByRole('button', { name: `Actions for vial ${label}` }).click()
  await page.getByRole('menuitem', { name: 'Change state' }).click()
  const change = page.getByRole('dialog', { name: `Change the state of vial ${label}` })
  await expect(change).toHaveAccessibleDescription(/destroyed with a destruction record, in the Destruction section of this tab/)
  await change.getByRole('combobox', { name: 'New state' }).selectOption({ label: 'To destroy' })
  await change.getByRole('textbox', { name: 'Reason' }).fill('The tube cracked in the freezer.')
  await change.getByRole('button', { name: 'Save state' }).click()
  await expect(change).toBeHidden()
  const vials = page.getByRole('table', { name: 'Vials' })
  await expect(vials.getByRole('row', { name: new RegExp(label) })).toContainText('To destroy')

  // The record of a regulated strain asks how the inactivation was verified, and waits.
  const section = page.getByRole('region', { name: 'Destruction', exact: true })
  await section.getByRole('button', { name: 'Record a destruction' }).click()
  const recording = page.getByRole('dialog', { name: 'Record a destruction' })
  await expect(recording.getByRole('checkbox', { name: label })).toBeChecked()
  await recording.getByRole('textbox', { name: 'Reason' }).fill('The tube cracked: the material is destroyed.')
  await recording.getByRole('button', { name: 'Record for confirmation' }).click()
  await expect(recording.getByRole('textbox', { name: 'Verification of the inactivation' })).toHaveAccessibleDescription(/Say how the inactivation was verified/)
  await recording.getByRole('textbox', { name: 'Verification of the inactivation' }).fill('Spore strip in the load: no growth after 7 days.')
  await recording.getByRole('button', { name: 'Record for confirmation' }).click()
  await expect(recording).toBeHidden()
  const records = section.getByRole('table', { name: 'Destruction records' })
  await expect(records.getByRole('row').nth(1)).toContainText('Waits for a manager other than e2e-curator to confirm')
  await expect(records.getByRole('button', { name: /^Confirm/ })).toHaveCount(0)
  await expect(vials.getByRole('row', { name: new RegExp(label) })).toContainText('To destroy')
  expect(violations()).toEqual([])
  await curator.close()

  // The manager confirms the record they read: the vial is destroyed now.
  const manager = await browser.newContext({ storageState: signedInAs(username) })
  const second = await manager.newPage()
  await second.goto(`/labs/${made.lab}/strains/${made.strain}/material`)
  const waiting = second.getByRole('region', { name: 'Destruction', exact: true }).getByRole('table', { name: 'Destruction records' })
  const row = waiting.getByRole('row').nth(1)
  const number = (await row.getByRole('cell').first().textContent()) ?? ''
  await row.getByRole('button', { name: `Confirm destruction ${number}` }).click()
  const confirming = second.getByRole('alertdialog', { name: `Confirm destruction ${number}?` })
  await expect(confirming).toHaveAccessibleDescription(/recorded by e2e-curator\. Confirmed, the vials are destroyed and leave their boxes/)
  await confirming.getByRole('button', { name: 'Confirm destruction' }).click()
  await expect(confirming).toBeHidden()
  await expect(row).toContainText(`Destroyed. Recorded by e2e-curator, confirmed by ${username}`)
  await expect(second.getByRole('table', { name: 'Vials' }).getByRole('row', { name: new RegExp(label) })).toContainText('Destroyed')
  await manager.close()
})
