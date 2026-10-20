import { expect, test } from '@playwright/test'
import { RUN, Walk, acceptedStrain, batch, expandUnit, freezerWithBoxes, labId, openLab, openStrain, openUnit, setupAs } from './walk.js'

// A technician of Bacteriology (seed_dev): the bench work with batches, vials and boxes. The rows
// each task needs are made first by the lab's curator, through the API, named for the run.
const LAB = 'Bacteriology'
const technician = (id: string, task: string) => ({ id, role: 'technician' as const, task })

/** A strain of this run and a freezer of its own with the named boxes, made by the curator. */
async function bench(browser: Parameters<typeof setupAs>[0], tag: string, boxes: string[]) {
  const setup = await setupAs(browser, 'bac-curator')
  const lab = await labId(setup.page, LAB)
  const strain = await acceptedStrain(setup.page, lab, `Bacillus subtilis ${tag} ${RUN}`, 'Bacillus subtilis')
  const units = await freezerWithBoxes(setup.page, lab, `Freezer ${tag} ${RUN}`, boxes)
  return { ...setup, lab, strain, units, name: `Bacillus subtilis ${tag} ${RUN}`, freezer: `Freezer ${tag} ${RUN}` }
}

test('T1 preserve a fresh batch and put it in a box', async ({ browser }, info) => {
  const box = `Box p${RUN}`
  const s = await bench(browser, 'preserve', [box])
  await s.close()

  const w = await Walk.as(browser, info, 'bac-technician', technician('T1', 'Preserve a fresh batch and put it in a box'))
  await w.start()
  await openLab(w, LAB)
  await openStrain(w, s.name, new RegExp(s.name))
  await w.click(w.page.getByRole('button', { name: 'Preserve a batch' }))
  const dialog = w.page.getByRole('dialog', { name: /^Preserve a batch of BAC/ })
  await w.choose(dialog.getByRole('combobox', { name: 'Method' }), 'Frozen at -80')
  await w.choose(dialog.getByRole('combobox', { name: 'Purpose' }), 'Distribution')
  await w.type(dialog.getByRole('textbox', { name: 'Protectant' }), '10 % glycerol')
  await w.type(dialog.getByRole('textbox', { name: 'Number of vials' }), '4')
  const boxes = dialog.getByRole('combobox', { name: 'Box' })
  w.look()
  await w.choose(boxes, `${s.freezer} / Rack 1 / ${box}`)
  await w.click(dialog.getByRole('button', { name: 'Preserve batch' }))
  await expect(w.page.getByRole('table', { name: 'Vials' }).getByRole('row', { name: new RegExp(`${box}, A4`) })).toBeVisible()
  w.note('The box list holds every box of the lab by its path, with no free places shown, and it grows with the storage')
  await w.done()
})

test('T2 find where vial X is', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-technician', technician('T2', 'Find where vial BAC 29 / 2 / 7 is'))
  await w.start()
  await openLab(w, LAB)
  await openStrain(w, 'BAC 29', /^BAC 29 /)
  const row = w.page.getByRole('table', { name: 'Vials' }).getByRole('row', { name: /^BAC 29 \/ 2 \/ 7 / })
  const { total, at } = await w.screensOf(row)
  await w.read(row)
  await expect(row).toContainText('Freezer -80 A / Rack 1 / Box 1, A7')
  w.note(`No search by vial label: the label leads to the strain page, ${total} screens long, and the vial's row is on screen ${at}`)
  await w.shot('strain-page')
  await w.done()
})

test('T3 place freeze-dried ampoules into a box', async ({ browser }, info) => {
  const box = `Box l${RUN}`
  const s = await bench(browser, 'ampoules', [box])
  const labels = await batch(s.page, s.lab, s.strain.passage, { count: 3, method: 'lyophilised' })
  await s.close()

  const w = await Walk.as(browser, info, 'bac-technician', technician('T3', 'Place three freeze-dried ampoules into a box'))
  await w.start()
  await openLab(w, LAB)
  await openStrain(w, s.name, new RegExp(s.name))
  for (const [i, label] of labels.entries()) {
    await w.click(w.page.getByRole('button', { name: `Place vial ${label}` }))
    const dialog = w.page.getByRole('dialog', { name: `Place vial ${label}` })
    await w.choose(dialog.getByRole('combobox', { name: 'Box' }), `${s.freezer} / Rack 1 / ${box}`)
    if (i === 0) await w.shot('place-dialog')
    await w.choose(dialog.getByRole('combobox', { name: 'Row' }), 'A')
    await w.choose(dialog.getByRole('combobox', { name: 'Column' }), String(i + 1))
    await w.click(dialog.getByRole('button', { name: 'Place vial' }))
    await expect(dialog).toBeHidden()
  }
  await expect(w.page.getByRole('table', { name: 'Vials' }).getByRole('row', { name: new RegExp(`${box}, A3`) })).toBeVisible()
  w.note('One dialog per vial, the box chosen again each time, and row and column picked blind: the dialog does not show which places are free')
  await w.done()
})

test('T4 move the tubes of a failing freezer into another box by scanning', async ({ browser }, info) => {
  const target = `Box s${RUN}`
  const s = await bench(browser, 'rescue', [`Box r${RUN}`, target])
  const tubes = await batch(s.page, s.lab, s.strain.passage, { count: 4, box: s.units.boxes[0] })
  await s.close()

  const w = await Walk.as(browser, info, 'bac-technician', technician('T4', 'Scan four tubes from a failing freezer into another box'))
  await w.start()
  await openLab(w, LAB)
  await w.click(w.page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Storage' }))
  const freezer = new RegExp(`^${s.freezer}, freezer`)
  await expandUnit(w, [freezer, /^Rack 1, rack/])
  await openUnit(w, [freezer, /^Rack 1, rack/, new RegExp(`^${target}, box`)])
  await expect(w.page.getByRole('heading', { level: 1, name: target })).toBeVisible()
  const code = w.page.getByRole('textbox', { name: 'Vial label or barcode' })
  for (const tube of tubes) {
    await w.type(code, tube) // the scanner types the label, and after a move the focus is on the grid
    await w.press('Enter') // Find
    await expect(w.page.getByRole('status')).toHaveText(`${tube} found. Choose an empty position and press Enter, or Escape to cancel.`)
    await w.press('Enter') // into the first empty position
    await expect(w.page.getByRole('status')).toHaveText(new RegExp(`^${tube} moved to [A-I]\\d\\.$`))
    await expect(code).not.toBeFocused()
  }
  w.note('After each placement focus stays on the grid, so the next scan needs a click back into the field')
  await w.done()
})

test('T5 rearrange a box: move a vial to another position', async ({ browser }, info) => {
  const box = `Box m${RUN}`
  const s = await bench(browser, 'rearrange', [box])
  const labels = await batch(s.page, s.lab, s.strain.passage, { count: 3, box: s.units.boxes[0] })
  await s.close()

  const w = await Walk.as(browser, info, 'bac-technician', technician('T5', 'Move a vial to another position in its box'))
  await w.start()
  await openLab(w, LAB)
  await w.click(w.page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Storage' }))
  const freezer = new RegExp(`^${s.freezer}, freezer`)
  await expandUnit(w, [freezer, /^Rack 1, rack/])
  await openUnit(w, [freezer, /^Rack 1, rack/, new RegExp(`^${box}, box`)])
  const grid = w.page.getByRole('grid', { name: `Positions of ${box}` })
  await w.click(grid.getByRole('gridcell', { name: `A1, ${labels[0] ?? ''}, available` }))
  await w.click(grid.getByRole('gridcell', { name: 'C4, empty' }))
  await expect(w.page.getByRole('status')).toHaveText(`${labels[0] ?? ''} moved to C4.`)
  await w.done()
})

test('T6 revive a vial to start a subculture', async ({ browser }, info) => {
  const s = await bench(browser, 'revive', [`Box v${RUN}`])
  const labels = await batch(s.page, s.lab, s.strain.passage, { count: 2, box: s.units.boxes[0] })
  await s.close()

  const w = await Walk.as(browser, info, 'bac-technician', technician('T6', 'Revive a vial to start a subculture'))
  await w.start()
  await openLab(w, LAB)
  await openStrain(w, s.name, new RegExp(s.name))
  await w.click(w.page.getByRole('button', { name: `Revive vial ${labels[0] ?? ''}` }))
  const dialog = w.page.getByRole('alertdialog', { name: `Revive vial ${labels[0] ?? ''}?` })
  await w.click(dialog.getByRole('button', { name: 'Revive vial' }))
  await expect(w.page.getByRole('table', { name: 'Passages' }).getByRole('row')).toHaveCount(3)
  w.note('The revival records no medium, temperature or growth result: the passage has no field for them')
  await w.done()
})

test('T7 record a cracked tube to be destroyed', async ({ browser }, info) => {
  const s = await bench(browser, 'cracked', [`Box c${RUN}`])
  const labels = await batch(s.page, s.lab, s.strain.passage, { count: 2, box: s.units.boxes[0] })
  await s.close()

  const label = labels[1] ?? ''
  const w = await Walk.as(browser, info, 'bac-technician', technician('T7', 'Record a cracked tube to be destroyed'))
  await w.start()
  await openLab(w, LAB)
  await openStrain(w, s.name, new RegExp(s.name))
  await w.click(w.page.getByRole('button', { name: `Change the state of vial ${label}` }))
  const dialog = w.page.getByRole('dialog', { name: `Change the state of vial ${label}` })
  await w.choose(dialog.getByRole('combobox', { name: 'New state' }), /destroy/i)
  await w.type(dialog.getByRole('textbox', { name: 'Reason' }), 'Tube cracked in the box.')
  await w.click(dialog.getByRole('button', { name: 'Save state' }))
  await expect(w.page.getByRole('table', { name: 'Vials' }).getByRole('row', { name: new RegExp(`^${label} To destroy`) })).toBeVisible()
  await w.done()
})

test('T8 record a viability check of a batch', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-technician', technician('T8', 'Record a viability check of a batch'))
  await w.start()
  await openLab(w, LAB)
  await openStrain(w, 'soil isolate DEP-1', /soil isolate DEP-1/)
  const batches = w.page.getByRole('table', { name: 'Batches' })
  await w.read(batches)
  await expect(batches.getByRole('button')).toHaveCount(0)
  w.impossible('No viability check: a batch has no check to record, and its status never leaves "Pending check"', '#17')
  await w.done()
})

test('T9 pull vials for an outgoing shipment', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-technician', technician('T9', 'Pull two vials for an outgoing shipment'))
  await w.start()
  await openLab(w, LAB)
  await openStrain(w, 'soil isolate DEP-1', /soil isolate DEP-1/)
  await w.click(w.page.getByRole('button', { name: 'Change the state of vial BAC 29 / 2 / 12' }))
  const states = w.page.getByRole('dialog').getByRole('combobox', { name: 'New state' })
  w.look()
  await expect(states.locator('option', { hasText: /Reserved|Distributed/ })).toHaveCount(0)
  await w.click(w.page.getByRole('dialog').getByRole('button', { name: 'Cancel' }))
  w.impossible('No shipment: a vial cannot be reserved or sent, and nothing lists what to pull', '#18')
  await w.done()
})

test('T10 see what waits for me today', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-technician', technician('T10', 'See what waits for me today'))
  await w.start()
  w.look()
  await openLab(w, LAB)
  await expect(w.page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link')).toHaveCount(2)
  w.look()
  w.impossible('No overview of vials to destroy, unplaced vials or batches to check: each is only on its own strain page', '#69')
  await w.done()
})
