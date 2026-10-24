import { expect, test } from '@playwright/test'
import { RUN, Walk, api, batchOf, expandUnit, labId, openLab, findStrain, openStrains, openTab, openUnit, passAll, release, requestFor, setupAs, supplyStrain } from './walk.js'

// A viewer of Bacteriology (seed_dev): someone who reads the catalogue and the stock, a student,
// a colleague from another group or a quality officer, and changes nothing.
const LAB = 'Bacteriology'
const viewer = (id: string, task: string) => ({ id, role: 'viewer' as const, task })

test('V1 find a strain by its number', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-viewer', viewer('V1', 'Find strain BAC 25 by its number'))
  await w.start()
  await openStrains(w, LAB)
  await findStrain(w, 'BAC 25', /^BAC 25 /)
  await expect(w.page.getByRole('heading', { level: 1, name: 'BAC 25' })).toBeVisible()
  w.note('Two screens to a strain whose number is known, through the strain list of the lab: no search from Home or the top bar')
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
  await openStrains(w, LAB)
  await findStrain(w, 'BAC 29', /^BAC 29 /)
  await openTab(w, 'Material')
  const row = w.page.getByRole('table', { name: 'Vials' }).getByRole('row', { name: /^BAC 29 \/ 1 \/ 3 / })
  await w.read(row)
  await expect(row).toContainText('LN2 tank 1 / Canister A / Seed stock 1, A3')
  await w.done()
})

test('V4 can the collection supply this strain now', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-viewer', viewer('V4', 'Can the collection supply BAC 29 now'))
  await w.start()
  await openStrains(w, LAB)
  await findStrain(w, 'BAC 29', /^BAC 29 /)
  await openTab(w, 'Material')
  const answer = w.page.getByText(/^Available for distribution:/)
  await w.read(answer)
  // seed_dev: batch 2 is released distribution stock of 12 vials. One is used up by its checks, and the seeded requests reserved or shipped three more.
  await expect(answer).toHaveText('Available for distribution: 8 vials, from released batch 2.')
  w.note('The answer is one line above the batch table on the Material tab, and the terms that say whether the use is allowed are on another tab, Overview')
  await w.done()
})

test('V5 see a strain\'s history', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-viewer', viewer('V5', 'See the history of a reclassified strain'))
  await w.start()
  await openStrains(w, LAB)
  await findStrain(w, 'Fictivibrio', /Fictivibrio exempli/)
  await openTab(w, 'History')
  const history = w.page.getByRole('list', { name: 'History, newest first' })
  await expect(history).toContainText(/identified BAC \d+ anew/)
  await w.read(history)
  await w.shot('strain-history')
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
  await openStrains(w, LAB)
  await findStrain(w, 'BAC 29', /^BAC 29 /)
  // seed_dev: the terms of BAC 29 permit teaching. They show on the Overview, to a viewer too (#78).
  const uses = w.page.getByRole('table', { name: 'Uses of the terms in force' })
  await w.read(uses)
  await expect(uses.getByRole('row', { name: /^Teaching / })).toContainText('Permitted')
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
  await openStrains(w, LAB)
  await findStrain(w, 'BAC 18', /^BAC 18 /)
  w.look(2)
  await expect(w.page.getByText(/medium|°C/i)).toHaveCount(0)
  w.impossible('No growth conditions anywhere: the strain and its passages have no medium, temperature or atmosphere')
  await w.done()
})

test('V10 see which vials are reserved for a request', async ({ browser }, info) => {
  const setup = await setupAs(browser, 'bac-curator')
  const lab = await labId(setup.page, LAB)
  const strain = await supplyStrain(setup.page, lab, `Bacillus subtilis reserved ${RUN}`, 'Bacillus subtilis')
  const made = await batchOf(setup.page, lab, strain.passage, 4)
  await setup.close()
  const bench = await setupAs(browser, 'bac-technician')
  await passAll(bench.page, lab, made.id, made.vials[0]?.id ?? '')
  await bench.close()
  const curator = await setupAs(browser, 'bac-curator')
  await release(curator.page, lab, made.id)
  const request = await requestFor(curator.page, lab, strain.id, 1, `Reserved for walkthrough ${RUN}.`)
  await api(curator.page, lab, `requests/${request.id}/approve/`, { reason: '' })
  await curator.close()

  const w = await Walk.as(browser, info, 'bac-viewer', viewer('V10', 'See which vials are reserved for a request'))
  await w.start()
  await openLab(w, LAB)
  await w.click(w.page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Requests' }))
  await w.type(w.page.getByRole('searchbox', { name: 'Number, requester or strain' }), strain.number)
  await w.press('Enter')
  await w.click(w.page.getByRole('table', { name: 'Requests' }).getByRole('link', { name: `Request ${request.number}` }))
  const reserved = w.page.getByRole('table', { name: 'Strains' }).getByRole('row').nth(1).getByRole('cell').nth(4)
  await expect(reserved).toHaveText(new RegExp(`^${strain.number} / 1 / \\d+$`))
  await w.read(reserved)
  w.note('Reserved vials are found request by request: no list of what the lab holds reserved, and the strain page says nothing of its reserved vials', '#69')
  await w.done()
})
