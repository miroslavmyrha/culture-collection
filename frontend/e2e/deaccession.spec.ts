import { expect, test } from '@playwright/test'
import { signedInAs } from './support.js'

// Walkthrough C10 (#20): a curator deaccessions a strain that no longer grows, against the real
// API. The strain, its storage and its two vials are this run's own, made through the API with
// e2e-curator's session: strains are never deleted, so the spec finds its own by a run-unique
// name. Testella exempli is invented and has no restriction here, so one person may do it.

test.describe.configure({ timeout: 120_000 })

const RUN = Date.now().toString(36)
const NAME = `Testella exempli gone ${RUN}`

test('C10: a curator deaccessions a strain that no longer grows; its vials are to be destroyed and the list hides it', async ({ browser }) => {
  const context = await browser.newContext({ storageState: signedInAs('e2e-curator') })
  const page = await context.newPage()
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
        restrictions: [],
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

  // From the strain's page, its header's menu.
  await page.goto(`/labs/${made.lab}/strains/${made.strain}`)
  await expect(page.getByRole('heading', { level: 1, name: made.number })).toBeVisible()
  await page.getByRole('button', { name: `Actions for ${made.number}` }).click()
  await page.getByRole('menuitem', { name: 'Deaccession', exact: true }).click()
  const dialog = page.getByRole('alertdialog', { name: `Deaccession ${made.number}?` })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused()
  await dialog.getByRole('combobox', { name: 'Cause' }).selectOption({ label: 'No longer grows' })
  await dialog.getByRole('textbox', { name: 'Reason' }).fill('No growth after three revivals on two media.')
  await dialog.getByRole('button', { name: 'Deaccession', exact: true }).click()
  await expect(dialog).toBeHidden()

  // The strain stays, with how it left; it changes no more.
  await expect(page.getByRole('list', { name: 'Biosafety and status' }).getByText('Deaccessioned')).toBeVisible()
  const left = page.getByRole('region', { name: 'Deaccession', exact: true })
  await expect(left).toContainText('No longer grows')
  await expect(left).toContainText('No growth after three revivals on two media.')
  await expect(page.getByRole('button', { name: `Actions for ${made.number}` })).toHaveCount(0)
  await expect(page.getByText('No vial of this strain was distributed.')).toBeVisible()

  // Its vials stay in their box, to be destroyed.
  await page.getByRole('navigation', { name: 'Strain sections' }).getByRole('link', { name: 'Material' }).click()
  const vials = page.getByRole('table', { name: 'Vials' })
  await expect(vials.getByRole('row')).toHaveCount(3)
  for (const row of [1, 2]) {
    await expect(vials.getByRole('row').nth(row)).toContainText('To destroy')
    await expect(vials.getByRole('row').nth(row)).toContainText(`Freezer d${RUN} / Rack 1 / Box 1`)
  }

  // The list leaves it out until the status filter asks for it.
  await page.goto(`/labs/${made.lab}/strains?search=${encodeURIComponent(NAME)}`)
  const strains = page.getByRole('table', { name: 'Strains' })
  await expect(page.getByRole('heading', { level: 1, name: 'Strains of E2E lab' })).toBeVisible()
  await expect(page.getByText('No strain matches these filters.')).toBeVisible()
  await expect(strains.getByRole('row', { name: new RegExp(NAME) })).toHaveCount(0)
  await page.getByRole('combobox', { name: 'Status' }).selectOption({ label: 'Deaccessioned' })
  await expect(page.getByRole('table', { name: 'Strains' }).getByRole('row', { name: new RegExp(NAME) })).toBeVisible()
  await context.close()
})
