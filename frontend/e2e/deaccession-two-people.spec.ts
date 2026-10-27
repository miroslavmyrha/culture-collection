import { expect, test } from '@playwright/test'
import { signedInAs, username } from './support.js'

// A regulated strain leaves the collection by two people (#20, ADR 0009): e2e-curator proposes
// it on the strain page, and the e2e user, a manager, confirms it there. The strain, its storage
// and its vials are this run's own, made through the API with the curator's session. Testella
// exempli is invented, so its GMO entry states nothing about a real organism.

test.describe.configure({ timeout: 120_000 })

const RUN = Date.now().toString(36)
const NAME = `Testella exempli two ${RUN}`

test('a curator proposes the deaccession of a regulated strain and a manager confirms it', async ({ browser }) => {
  const curator = await browser.newContext({ storageState: signedInAs('e2e-curator') })
  const page = await curator.newPage()
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
        restrictions: [{ kind: 'gmo', reference: `MŽP/DEV/${run} (invented example)`, act: '', gmo_category: 1 }],
      })
      const strain = accepted.strain?.public_id ?? ''
      const freezer = await send('storage-units/', { kind: 'freezer', name: `Freezer t${run}`, max_risk_group: 2 })
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

  // The curator: one person cannot take a regulated strain out, so the menu proposes it.
  await page.goto(`/labs/${made.lab}/strains/${made.strain}`)
  await expect(page.getByRole('heading', { level: 1, name: made.number })).toBeVisible()
  await page.getByRole('button', { name: `Actions for ${made.number}` }).click()
  await expect(page.getByRole('menuitem', { name: 'Deaccession', exact: true })).toHaveCount(0)
  await page.getByRole('menuitem', { name: 'Propose deaccession' }).click()
  const proposing = page.getByRole('dialog', { name: `Propose to deaccession ${made.number}` })
  await proposing.getByRole('combobox', { name: 'Cause' }).selectOption({ label: 'Contaminated' })
  await proposing.getByRole('textbox', { name: 'Reason' }).fill('Mixed culture on every plate since the last subculture.')
  await proposing.getByRole('button', { name: 'Propose' }).click()
  await expect(proposing).toBeHidden()
  const proposed = page.getByRole('region', { name: 'Proposed deaccession' })
  await expect(proposed).toContainText('You proposed it: a different manager confirms.')
  await expect(proposed.getByRole('button', { name: 'Confirm deaccession' })).toHaveCount(0)
  await expect(page.getByRole('list', { name: 'Biosafety and status' }).getByText('Active')).toBeVisible()
  await curator.close()

  // The manager confirms the proposal they read.
  const manager = await browser.newContext({ storageState: signedInAs(username) })
  const second = await manager.newPage()
  await second.goto(`/labs/${made.lab}/strains/${made.strain}`)
  const waiting = second.getByRole('region', { name: 'Proposed deaccession' })
  await expect(waiting).toContainText('Waiting for your confirmation.')
  await waiting.getByRole('button', { name: 'Confirm deaccession' }).click()
  const confirming = second.getByRole('alertdialog', { name: `Deaccession ${made.number}?` })
  await expect(confirming.getByText('Reason given: Mixed culture on every plate since the last subculture.')).toBeVisible()
  await confirming.getByRole('button', { name: 'Deaccession', exact: true }).click()
  await expect(confirming).toBeHidden()
  await expect(second.getByRole('list', { name: 'Biosafety and status' }).getByText('Deaccessioned')).toBeVisible()
  await expect(second.getByRole('region', { name: 'Deaccession', exact: true })).toContainText('Contaminated')
  await expect(second.getByRole('region', { name: 'Proposed deaccession' })).toHaveCount(0)
  await second.getByRole('navigation', { name: 'Strain sections' }).getByRole('link', { name: 'Material' }).click()
  const vials = second.getByRole('table', { name: 'Vials' })
  await expect(vials.getByRole('row')).toHaveCount(3)
  for (const row of [1, 2]) await expect(vials.getByRole('row').nth(row)).toContainText('To destroy')
  await manager.close()
})
