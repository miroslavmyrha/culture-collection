import { expect, test } from '@playwright/test'
import { Walk, expandUnit, openLab, openStrain, openUnit } from './walk.js'

// A viewer of Bacteriology (seed_dev): someone who reads the catalogue and the stock, a student,
// a colleague from another group or a quality officer, and changes nothing.
const LAB = 'Bacteriology'
const viewer = (id: string, task: string) => ({ id, role: 'viewer' as const, task })

test('V1 find a strain by its number', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-viewer', viewer('V1', 'Find strain BAC 25 by its number'))
  await w.start()
  await openLab(w, LAB)
  await openStrain(w, 'BAC 25', /^BAC 25 /)
  await expect(w.page.getByRole('heading', { level: 1, name: 'BAC 25' })).toBeVisible()
  w.note('Four screens to a strain whose number is known: no search from Home or the top bar')
  await w.done()
})

test('V2 find all strains of a genus in risk group 2', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-viewer', viewer('V2', 'Find all Staphylococcus strains in risk group 2'))
  await w.start()
  await openLab(w, LAB)
  await w.click(w.page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Strains' }))
  const filters = w.page.getByRole('form', { name: 'Filter strains' })
  await w.type(filters.getByRole('combobox', { name: 'Taxon' }), 'Staphylo')
  await w.click(w.page.getByRole('option', { name: /^Staphylococcus\b/ }).first())
  await w.choose(filters.getByRole('combobox', { name: 'Risk group' }), '2')
  await w.click(filters.getByRole('button', { name: 'Search' }))
  const table = w.page.getByRole('table', { name: 'Strains' })
  await expect(table.getByRole('row', { name: /Staphylococcus aureus/ }).first()).toBeVisible()
  w.look()
  await w.done()
})

test('V3 find where vial X is', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-viewer', viewer('V3', 'Find where vial BAC 29 / 1 / 3 is'))
  await w.start()
  await openLab(w, LAB)
  await openStrain(w, 'BAC 29', /^BAC 29 /)
  const row = w.page.getByRole('table', { name: 'Vials' }).getByRole('row', { name: /^BAC 29 \/ 1 \/ 3 / })
  await w.read(row)
  await expect(row).toContainText('LN2 tank 1 / Canister A / Seed stock 1, A3')
  await w.done()
})

test('V4 can the collection supply this strain now', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-viewer', viewer('V4', 'Can the collection supply BAC 29 now'))
  await w.start()
  await openLab(w, LAB)
  await openStrain(w, 'BAC 29', /^BAC 29 /)
  const batches = w.page.getByRole('table', { name: 'Batches' })
  await w.read(batches)
  await expect(batches.getByRole('row', { name: /Distribution stock .* Pending check/ }).first()).toBeVisible()
  w.look(2) // purpose, status and vials per batch, then the sum in the head
  w.note('The answer is read from three columns of the batch table and added up in the head: no "available for distribution" figure')
  await w.done()
})

test('V5 see a strain\'s history', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-viewer', viewer('V5', 'See the history of a reclassified strain'))
  await w.start()
  await openLab(w, LAB)
  await openStrain(w, 'Fictivibrio', /Fictivibrio exempli/)
  const identifications = w.page.getByRole('table', { name: 'Identification history' })
  await w.read(identifications)
  await expect(identifications.getByRole('row')).toHaveCount(3)
  await w.shot('strain-page')
  w.impossible('Only the identifications: passages, batches, moves and state changes of the vials have no time line', '#19')
  await w.done()
})

test('V6 see what a box holds', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-viewer', viewer('V6', 'See what Box 1 in Freezer -80 A holds'))
  await w.start()
  await openLab(w, LAB)
  await w.click(w.page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Storage' }))
  const freezer = /^Freezer -80 A, freezer/
  await expandUnit(w, [freezer, /^Rack 1, rack/])
  await openUnit(w, [freezer, /^Rack 1, rack/, /^Box 1, box/])
  const grid = w.page.getByRole('grid', { name: 'Positions of Box 1' })
  await w.read(grid)
  await expect(grid.getByRole('gridcell', { name: /^A1, BAC 29 \/ 2 \/ 1/ })).toBeVisible()
  w.note('The grid shows labels (strain number, batch, vial) but no organism: what is stored where needs a strain page per number')
  await w.done()
})

test('V7 may this strain be used for teaching', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-viewer', viewer('V7', 'May strain BAC 29 be used for teaching'))
  await w.start()
  await openLab(w, LAB)
  await openStrain(w, 'BAC 29', /^BAC 29 /)
  w.look()
  await expect(w.page.getByRole('heading', { name: /Terms/ })).toHaveCount(0)
  await w.click(w.page.getByRole('link', { name: `Strains of ${LAB}` }))
  await w.click(w.page.getByRole('link', { name: `Back to ${LAB}` }))
  await expect(w.page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Deposits' })).toHaveCount(0)
  w.look()
  w.impossible('The terms of use live only on the deposit, which a viewer may not open: the strain page does not show the uses it allows')
  await w.done()
})

test('V8 find soil isolates from Czechia', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-viewer', viewer('V8', 'Find the soil isolates from Czechia'))
  await w.start()
  await openLab(w, LAB)
  await w.click(w.page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Strains' }))
  await w.type(w.page.getByRole('searchbox', { name: 'Number or name' }), 'soil')
  await w.press('Enter')
  w.look()
  await expect(w.page.getByRole('table', { name: 'Strains' }).getByRole('row', { name: /soil/ }).first()).toBeVisible()
  w.impossible('The search reads the number, the name as received and the taxon, not the isolation source or the country: a soil isolate whose name does not say so is not found')
  await w.done()
})

test('V9 look up how to grow a strain', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-viewer', viewer('V9', 'Look up the medium and temperature to grow BAC 18'))
  await w.start()
  await openLab(w, LAB)
  await openStrain(w, 'BAC 18', /^BAC 18 /)
  w.look(2)
  await expect(w.page.getByText(/medium|°C/i)).toHaveCount(0)
  w.impossible('No growth conditions anywhere: the strain and its passages have no medium, temperature or atmosphere')
  await w.done()
})
