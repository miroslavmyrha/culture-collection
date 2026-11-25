import { expect, test } from '@playwright/test'
import { axe, runId, signedInAs, username, watchCsp } from './support.js'

// Catalogue import (#70) against the real API. seed_e2e makes the e2e user the manager of
// "E2E lab", with the depositor "E2E Depositor" and the taxon Bacillus subtilis. Each run imports
// one strain under a former number made unique per run: numbers are never reused and nothing is
// deleted, so the strain takes the lab's next number and the test finds it by the former one.

const RUN = runId()
const FORMER = `OLD-${RUN}`
const HEADER = [
  'accession_number', 'name_as_received', 'depositor', 'depositor_institution', 'received_on', 'condition', 'note',
  'taxon', 'taxon_authority', 'identified_on', 'identification_method', 'risk_group', 'risk_group_basis', 'risk_group_entry',
  'animal_pathogenicity', 'plant_pathogenicity', 'isolation_source', 'country_of_origin', 'isolation_date', 'restrictions',
  'abs_scope', 'uses', 'mta',
]

function csv(taxon: string): Buffer {
  const values: Record<string, string> = {
    accession_number: FORMER,
    name_as_received: `B. subtilis import ${RUN}`,
    depositor: 'E2E Depositor',
    received_on: '2019-05-14',
    note: 'Moved in by an end-to-end test (invented example).',
    taxon,
    identified_on: '2019-06-01',
    identification_method: '16S rRNA gene sequence',
    risk_group: '1',
    risk_group_basis: 'Imported by an end-to-end test (invented example).',
  }
  const row = HEADER.map((c) => values[c] ?? '').join(',')
  return Buffer.from(`${HEADER.join(',')}\n${row}\n`, 'utf-8')
}

test('a manager checks a catalogue, sees the row error, imports the corrected file and finds the strain by its former number', async ({ browser }) => {
  const context = await browser.newContext({ storageState: signedInAs(username), viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  const violations = await watchCsp(page)
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await page.getByRole('link', { name: 'Strains' }).click()
  await page.getByRole('link', { name: 'Import a catalogue' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Import a catalogue into E2E lab' })).toBeVisible()
  await expect(page).toHaveTitle('Import a catalogue into E2E lab | Culture collection')

  // The template downloads with the session: its first line is the header the import reads.
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Download the template' }).click()])
  const template = await download.createReadStream()
  const chunks: Buffer[] = []
  for await (const chunk of template) chunks.push(Buffer.from(chunk))
  expect(Buffer.concat(chunks).toString('utf-8').split('\n')[0]).toBe(HEADER.join(','))

  // A taxon the lab does not know is an error on its row and column, and nothing can be imported.
  const file = page.getByLabel('Catalogue file')
  await file.setInputFiles({ name: 'catalogue.csv', mimeType: 'text/csv', buffer: csv('Nosuchia fakeus') })
  await page.getByRole('button', { name: 'Check the file' }).click()
  await expect(page.getByText(/^1 error in 1 row\./)).toBeVisible()
  await expect(page.getByRole('table').getByRole('row').nth(1)).toHaveText(/^2taxon/)
  await expect(page.getByRole('button', { name: /^Import/ })).toHaveCount(0)
  expect(await axe(page, 'main')).toEqual([])

  // The corrected file checks clean and imports with a reason.
  await file.setInputFiles({ name: 'catalogue.csv', mimeType: 'text/csv', buffer: csv('Bacillus subtilis') })
  await page.getByRole('button', { name: 'Check the file' }).click()
  await expect(page.getByText('The row can be imported.')).toBeVisible()
  await page.getByRole('textbox', { name: /Reason/ }).fill('End-to-end test of the catalogue import.')
  await page.getByRole('button', { name: 'Import 1 strain' }).click()
  await expect(page.getByText('Imported 1 strain.')).toBeVisible()
  const imported = page.getByRole('list', { name: 'Imported strains' }).getByRole('listitem')
  await expect(imported).toHaveText(new RegExp(`^E2E \\d+ \\(formerly ${FORMER}\\)$`))

  // Search by the former number finds it, and the strain page shows the number.
  await page.goto(page.url().replace(/catalogue-import$/, `strains?search=${FORMER}`))
  await page.getByRole('link', { name: /^E2E \d+$/ }).first().click()
  await expect(page.getByRole('definition').filter({ hasText: FORMER })).toBeVisible()
  expect(violations()).toEqual([])
  await context.close()
})
