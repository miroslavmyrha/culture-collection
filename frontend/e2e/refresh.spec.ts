import { expect, test } from '@playwright/test'
import { signedInAs, username } from './support.js'

// A write in one part of the app refreshes what another part shows (#64), against the real API.
// The strain, its restriction, storage and vial are this run's own, made through the API with
// the session auth.setup.ts signed in: strains and vials are never deleted and a restriction ends
// only once, so no other spec's data changes. Testella exempli is invented, so a GMO entry on it
// states nothing about a real organism.

const RUN = Date.now().toString(36)

test("ending a restriction shows the vial's place on the strain page without a reload", async ({ browser }) => {
  const context = await browser.newContext({ storageState: signedInAs(username) })
  const page = await context.newPage()
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeVisible()

  const made = await page.evaluate(async (run) => {
    await fetch('/api/v1/auth/csrf/')
    const token = decodeURIComponent(/(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? '')
    const lab = location.pathname.split('/')[2] ?? ''
    const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': token }
    const send = async (path: string, body: unknown) => {
      const response = await fetch(`/api/v1/labs/${lab}/${path}`, { method: 'POST', headers, body: JSON.stringify(body) })
      if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`)
      const created: { public_id: string; strain?: { public_id: string } | null } = await response.json()
      return created
    }
    const read = async <T>(url: string): Promise<T> => {
      const body: T = await (await fetch(url, { headers })).json()
      return body
    }
    const depositors = await read<{ results: { public_id: string }[] }>(`/api/v1/labs/${lab}/depositors/?search=E2E`)
    const uses = ['research_noncommercial', 'research_commercial', 'teaching', 'diagnostics', 'production', 'reference_qc', 'patent_deposit_related', 'redistribution']
    const deposit = await send('deposits/', {
      depositor: depositors.results[0]?.public_id,
      received_on: new Date().toLocaleDateString('sv'),
      condition: 'intact',
      name_as_received: `Testella exempli refresh ${run}`,
      terms: { mta: null, abs_scope: 'unknown', uses: uses.map((use) => ({ use, decision: 'on_request' })) },
    })
    await send(`deposits/${deposit.public_id}/start-check/`, {})
    const taxa = await read<{ results: { public_id: string; name: string }[] }>('/api/v1/taxa/?search=exempli')
    const reference = `MŽP/DEV/${run} (invented example)`
    const accepted = await send(`deposits/${deposit.public_id}/accept/`, {
      taxon: taxa.results.find((t) => t.name === 'Testella exempli')?.public_id,
      identified_on: new Date().toLocaleDateString('sv'),
      identification_method: 'MALDI-TOF MS',
      risk_group: 1,
      animal_pathogenicity: 'unknown',
      plant_pathogenicity: 'unknown',
      isolation_source: '',
      country_of_origin: '',
      isolation_date: '',
      restrictions: [{ kind: 'gmo', reference, act: '', gmo_category: 1 }],
    })
    const strain = accepted.strain?.public_id ?? ''
    const freezer = await send('storage-units/', { kind: 'freezer', name: `Freezer r${run}`, max_risk_group: 2 })
    const rack = await send('storage-units/', { kind: 'rack', name: 'Rack 1', parent: freezer.public_id })
    const types = await read<{ results: { public_id: string; name: string }[] }>('/api/v1/box-types/')
    const box = await send('storage-units/', { kind: 'box', name: 'Box 1', parent: rack.public_id, box_type: types.results.find((t) => t.name === '81-place cryobox (9 x 9)')?.public_id })
    const passages = await read<{ results: { public_id: string }[] }>(`/api/v1/labs/${lab}/passages/?strain=${strain}`)
    await send('batches/', {
      passage: passages.results[0]?.public_id,
      method: 'cryo_minus80',
      purpose: 'seed',
      cryoprotectant: '10 % glycerol',
      preserved_on: new Date().toLocaleDateString('sv'),
      vial_count: 1,
      box: box.public_id,
    })
    return { lab, strain, reference }
  }, RUN)

  await page.goto(`/labs/${made.lab}/strains/${made.strain}/material`)
  const vials = page.getByRole('table', { name: 'Vials' })
  await expect(vials.getByRole('row').nth(1)).toContainText('Hidden: regulated strain')
  // Marks this document: a reload would lose it.
  await page.evaluate(() => document.documentElement.setAttribute('data-run', 'kept'))

  // The restriction ends from its row on the Overview tab, the vial shows on Material (#19).
  const tabs = page.getByRole('navigation', { name: 'Strain sections' })
  await tabs.getByRole('link', { name: 'Overview' }).click()
  await page.getByRole('button', { name: `End restriction ${made.reference}` }).click()
  const dialog = page.getByRole('dialog', { name: `End the restriction ${made.reference}` })
  await dialog.getByRole('textbox', { name: 'Reason' }).fill('the construct was destroyed')
  await dialog.getByRole('button', { name: 'End restriction' }).click()
  await expect(dialog).toBeHidden()
  await tabs.getByRole('link', { name: 'Material' }).click()
  await expect(vials.getByRole('row').nth(1)).toContainText(`Freezer r${RUN} / Rack 1 / Box 1, A1`)
  await expect(vials.getByRole('button', { name: /Reveal the location/ })).toHaveCount(0)
  await expect(page.locator('html')).toHaveAttribute('data-run', 'kept')
  await context.close()
})
