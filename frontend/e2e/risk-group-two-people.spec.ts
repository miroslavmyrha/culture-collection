import { expect, test } from '@playwright/test'
import { riskGroupBasis, signedInAs, username } from './support.js'

// A risk group drops by two people (#174, ADR 0009): e2e-curator raises a strain of this run to
// group 2 in one step, proposes group 1 with the basis it rests on, and the e2e user, a manager,
// confirms it on the strain page. The strain is this run's own, made through the API with the
// curator's session. Testella exempli is invented, so no real organism is shown with a group it
// does not have.

const RUN = Date.now().toString(36)
const NAME = `Testella exempli group ${RUN}`
const BASIS = 'NV 361/2007 Sb., Příloha 7: the agent is in none of the groups 2 to 4.'

test('a curator proposes a lower risk group and a manager confirms it', async ({ browser }) => {
  const curator = await browser.newContext({ storageState: signedInAs('e2e-curator') })
  const page = await curator.newPage()
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeVisible()

  const made = await page.evaluate(
    async ({ name, basis }) => {
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
        restrictions: [],
      })
      const strain = accepted.strain?.public_id ?? ''
      // One person raises a group: it only tightens the rules.
      await send(`strains/${strain}/risk-group/`, { risk_group: 2, basis: basis, reason: 'Reassessed at intake.' })
      return { lab, strain, number: accepted.strain?.accession_number ?? '' }
    },
    { name: NAME, basis: BASIS },
  )

  // The curator: a lower group becomes a proposal, and nothing of the strain changes yet.
  await page.goto(`/labs/${made.lab}/strains/${made.strain}`)
  await expect(page.getByRole('heading', { level: 1, name: made.number })).toBeVisible()
  await page.getByRole('button', { name: `Actions for ${made.number}` }).click()
  await page.getByRole('menuitem', { name: 'Change risk group' }).click()
  const dialog = page.getByRole('dialog', { name: `Change the risk group of ${made.number}` })
  await dialog.getByRole('combobox', { name: 'Risk group' }).selectOption('1')
  await expect(dialog.getByRole('button', { name: 'Propose the lower group' })).toBeVisible()
  await dialog.getByRole('textbox', { name: 'Basis' }).fill(BASIS)
  await dialog.getByRole('textbox', { name: 'Reason' }).fill('Reassessed against the annex in force.')
  await dialog.getByRole('button', { name: 'Propose the lower group' }).click()
  await expect(dialog).toBeHidden()
  const proposed = page.getByRole('region', { name: 'Proposed risk group' })
  await expect(proposed).toContainText('You proposed it: a different manager confirms.')
  await expect(proposed.getByRole('button', { name: 'Confirm the lower risk group' })).toHaveCount(0)
  await expect(page.getByRole('list', { name: 'Biosafety and status' }).getByText('Risk group 2')).toBeVisible()
  await curator.close()

  // The manager confirms the proposal they read.
  const manager = await browser.newContext({ storageState: signedInAs(username) })
  const second = await manager.newPage()
  await second.goto(`/labs/${made.lab}/strains/${made.strain}`)
  const waiting = second.getByRole('region', { name: 'Proposed risk group' })
  await expect(waiting).toContainText('Waiting for your confirmation.')
  await waiting.getByRole('button', { name: 'Confirm the lower risk group' }).click()
  const confirming = second.getByRole('alertdialog', { name: 'Lower the risk group to 1?' })
  await expect(confirming.getByText(`Basis given: ${BASIS}`)).toBeVisible()
  await confirming.getByRole('button', { name: 'Lower the risk group' }).click()
  await expect(confirming).toBeHidden()
  await expect(second.getByRole('list', { name: 'Biosafety and status' }).getByText('Risk group 1')).toBeVisible()
  await expect(second.getByRole('region', { name: 'Proposed risk group' })).toHaveCount(0)
  await expect(second.getByRole('region', { name: 'Facts' })).toContainText(`Basis of the risk group${BASIS}`)
  await manager.close()
})
