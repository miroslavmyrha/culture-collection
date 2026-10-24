import { expect, test } from '@playwright/test'
import { RUN, Walk, acceptedStrain, api, batch, batchOf, freezerWithBoxes, labId, openLab, findStrain, openStrains, openWaiting, openUnit, passAll, receivedDeposit, release, setupAs, supplyStrain } from './walk.js'

// A curator of Bacteriology (seed_dev): intake, identification, storage and the strain's record.
const LAB = 'Bacteriology'
const curator = (id: string, task: string) => ({ id, role: 'curator' as const, task })

test('C1 receive a deposit and record its terms', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-curator', curator('C1', 'Receive a deposit and record its terms'))
  const name = `Bacillus subtilis walk ${RUN}`
  await w.start()
  // Home's quick action (#69), where the lab picker, the lab and its Deposits tab led before.
  await w.click(w.page.getByRole('region', { name: 'Quick actions' }).getByRole('link', { name: 'Receive a deposit' }))
  const form = w.page.getByRole('form', { name: 'Receive a deposit' })
  await w.type(form.getByRole('combobox', { name: 'Depositor' }), 'Vzor')
  await w.click(w.page.getByRole('option', { name: /Jana Vzorová/ }))
  await w.type(form.getByRole('textbox', { name: 'Name as received' }), name)
  await w.type(form.getByRole('textbox', { name: 'Passages stated by the depositor' }), '2')
  const uses = form.getByRole('group', { name: 'Uses' }).getByRole('combobox')
  for (let i = 0; i < 8; i++) await w.choose(uses.nth(i), i === 1 ? 'On request to the depositor' : 'Permitted')
  await w.choose(form.getByRole('combobox', { name: 'MTA' }), /^STD version 2/)
  await w.choose(form.getByRole('combobox', { name: 'ABS scope' }), 'Not in scope')
  await w.choose(form.getByRole('combobox', { name: 'Country of origin' }), 'Czechia')
  await w.type(form.getByRole('textbox', { name: 'Collection date' }), '2026-09')
  await w.shot('receive-form')
  await w.click(form.getByRole('button', { name: 'Record the deposit' }))
  await expect(w.page.getByRole('heading', { level: 1, name: `Deposit ${name}` })).toBeVisible()
  w.note('Eight separate use selects, each opened and chosen, with no "same as the MTA" or default set')
  await w.done()
})

test('C2 check a deposit and accept it as a strain', async ({ browser }, info) => {
  const name = `Bacillus subtilis check ${RUN}`
  const setup = await setupAs(browser, 'bac-curator')
  await receivedDeposit(setup.page, await labId(setup.page, LAB), name)
  await setup.close()

  const w = await Walk.as(browser, info, 'bac-curator', curator('C2', 'Check a deposit and accept it as a strain'))
  await w.start()
  // The deposit waits on Home (#69): one link, where the lab, its deposits and a search led before.
  await openWaiting(w, 'Deposits received', name)
  await w.click(w.page.getByRole('button', { name: 'Start checking' }))
  const form = w.page.getByRole('form', { name: 'Accept the deposit' })
  await w.type(form.getByRole('combobox', { name: 'Taxon' }), 'Bacillus subt')
  await w.click(w.page.getByRole('option', { name: /^Bacillus subtilis/ }))
  await w.type(form.getByRole('textbox', { name: 'Identification method' }), '16S rRNA gene sequence')
  await w.choose(form.getByRole('combobox', { name: 'Risk group' }), '1')
  await w.type(form.getByRole('textbox', { name: 'Isolation source' }), 'Garden soil')
  await w.click(form.getByRole('button', { name: 'Accept and add the strain' }))
  const strain = w.page.getByRole('link', { name: /^BAC \d+$/ })
  await expect(strain).toBeVisible()
  await w.click(strain)
  await expect(w.page.getByRole('heading', { level: 1, name: /^BAC \d+$/ })).toBeVisible()
  w.note('The check itself (purity plate, identity) is a button press, and its results have no place but the identification method text', '#17')
  await w.done()
})

test('C3 see what waits for me today', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-curator', curator('C3', 'See what waits for me today'))
  await w.start()
  // seed_dev: in Bacteriology a received deposit (DEP-3), one in checking (DEP-2), batch 3 of
  // BAC 29 pending its checks, two requests to decide and two to ship. Other tasks of the run add
  // their own, so the groups are read, not counted.
  const waiting = w.page.getByRole('region', { name: /^Waiting for you \(\d+\)$/ })
  for (const group of ['Deposits received', 'Deposits in checking', 'Batches waiting for their checks', 'Requests to decide', 'Requests to ship']) {
    await w.read(waiting.getByRole('region', { name: new RegExp(`^${group} \\(\\d+\\)$`) }))
  }
  await w.shot('home-waiting')
  w.note('Everything waits in one list on Home, but in groups by kind, not by what is most urgent: a manager-only request and an expiring permit sit in their own groups')
  await w.done()
})

test('C4 reclassify a strain after a new identification', async ({ browser }, info) => {
  const name = `Bacillus megaterium walk ${RUN}`
  const setup = await setupAs(browser, 'bac-curator')
  await acceptedStrain(setup.page, await labId(setup.page, LAB), name, 'Bacillus megaterium')
  await setup.close()

  const w = await Walk.as(browser, info, 'bac-curator', curator('C4', 'Reclassify a strain after a new identification'))
  await w.start()
  await openStrains(w, LAB)
  await findStrain(w, name, new RegExp(name))
  await w.click(w.page.getByRole('button', { name: 'Reclassify' }))
  const dialog = w.page.getByRole('dialog', { name: /^Reclassify BAC/ })
  await w.keys('Priestia meg') // the taxon field takes focus
  await w.click(w.page.getByRole('option', { name: /^Priestia megaterium/ }))
  await w.type(dialog.getByRole('textbox', { name: 'Method' }), 'Whole genome sequence (ANI)')
  await w.type(dialog.getByRole('textbox', { name: 'Reason' }), 'The genome places it in Priestia.')
  await w.click(dialog.getByRole('button', { name: 'Save identification' }))
  await expect(w.page.getByText(/^Priestia megaterium/).first()).toBeVisible()
  await w.done()
})

test('C5 find the strains that came from one depositor', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-curator', curator('C5', 'Find the strains that came from one depositor'))
  await w.start()
  await openLab(w, LAB)
  await w.click(w.page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Deposits' }))
  await w.choose(w.page.getByRole('combobox', { name: 'Status' }), 'Accepted')
  await w.type(w.page.getByRole('searchbox', { name: 'Name, depositor or number' }), 'Vzorová')
  await w.press('Enter')
  await expect(w.page.getByRole('table', { name: 'Deposits' }).getByRole('link', { name: /^BAC \d+$/ }).first()).toBeVisible()
  w.look(2)
  w.note('Only through the deposit list: the strain list has no depositor filter and the strain page does not name its deposit')
  await w.done()
})

test('C6 see what happened to a strain: its risk group and restriction changes', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-curator', curator('C6', 'See what happened to a strain (risk group, restrictions)'))
  await w.start()
  await openStrains(w, LAB)
  // seed_dev: BAC 27 is the Mockia vulgaris strain with the reassessment in its history. BAC 30 is a later deposit of the same taxon.
  await findStrain(w, 'BAC 27', /^BAC 27 /)
  w.look(3) // facts, restrictions, identification history
  await expect(w.page.getByRole('heading', { level: 2, name: 'Identification history' })).toBeVisible()
  await expect(w.page.getByText(/Reassessed after the list entry was checked/)).toHaveCount(0)
  await w.shot('strain-without-history')
  w.impossible('The risk group was lowered from 2 to 1: the page shows the ended restriction with its reason, but not that change, when, by whom or why', '#19')
  await w.done()
})

test('C7 move the racks out of a failing freezer and put it out of service', async ({ browser }, info) => {
  const failing = `Failing freezer ${RUN}`
  const backup = `Backup freezer ${RUN}`
  const setup = await setupAs(browser, 'bac-curator')
  const lab = await labId(setup.page, LAB)
  const units = await freezerWithBoxes(setup.page, lab, failing, [`Box f${RUN}`])
  const strain = await acceptedStrain(setup.page, lab, `Bacillus subtilis freezer ${RUN}`, 'Bacillus subtilis')
  await batch(setup.page, lab, strain.passage, { count: 3, box: units.boxes[0] })
  await api(setup.page, lab, 'storage-units/', { kind: 'freezer', name: backup, temperature_c: -80, max_risk_group: 2 })
  await setup.close()

  const w = await Walk.as(browser, info, 'bac-curator', curator('C7', 'Move the racks out of a failing freezer, put it out of service'))
  await w.start()
  await openLab(w, LAB)
  await w.click(w.page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Storage' }))
  await openUnit(w, [new RegExp(`^${failing}, freezer`)])
  await expect(w.page.getByRole('heading', { level: 1, name: failing })).toBeVisible()
  w.look()
  await w.shot('freezer-page')
  w.note('The freezer page lists its racks but not how many vials or which strains it holds, so the impact of the failure is unknown')
  await w.click(w.page.getByRole('table', { name: `What ${failing} holds` }).getByRole('link', { name: 'Rack 1' }))
  await w.click(w.page.getByRole('button', { name: 'Move' }))
  const move = w.page.getByRole('dialog', { name: 'Move Rack 1' })
  await w.choose(move.getByRole('combobox', { name: 'Into' }), backup)
  await w.type(move.getByRole('textbox', { name: 'Slot' }), '1')
  await w.click(move.getByRole('button', { name: 'Move' }))
  await expect(w.page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: backup })).toBeVisible()
  w.note('After the move the page stays on the rack: the way back to the failing freezer is through the tree again')
  await w.click(w.page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: `Storage of ${LAB}` }))
  await openUnit(w, [new RegExp(`^${failing}, freezer`)])
  await w.click(w.page.getByRole('button', { name: 'Put out of service' }))
  const status = w.page.getByRole('dialog', { name: `Put ${failing} out of service` })
  await w.type(status.getByRole('textbox', { name: 'Reason' }), 'Compressor failed, temperature rose to -40 °C.')
  await w.click(status.getByRole('button', { name: 'Out of service' }))
  await expect(w.page.getByText('Out of service').first()).toBeVisible()
  await w.done()
})

test('C8 release a batch after its checks', async ({ browser }, info) => {
  // A batch of this run, its three checks recorded by the lab's technician.
  const name = `Bacillus subtilis release ${RUN}`
  const setup = await setupAs(browser, 'bac-curator')
  const lab = await labId(setup.page, LAB)
  const strain = await acceptedStrain(setup.page, lab, name, 'Bacillus subtilis')
  const made = await batchOf(setup.page, lab, strain.passage, 3)
  await setup.close()
  const bench = await setupAs(browser, 'bac-technician')
  await passAll(bench.page, lab, made.id, made.vials[0]?.id ?? '')
  await bench.close()

  const w = await Walk.as(browser, info, 'bac-curator', curator('C8', 'Release a batch after its purity and viability checks'))
  await w.start()
  // The batch waits on Home for its release (#69).
  await openWaiting(w, 'Batches to release', `${strain.number} batch 1`)
  const batches = w.page.getByRole('table', { name: 'Batches' })
  await w.read(batches)
  await expect(batches.getByRole('row', { name: /All checks passed\. A curator releases it\./ })).toBeVisible()
  await w.click(batches.getByRole('button', { name: 'Checks of batch 1' }))
  await expect(w.page.getByRole('list', { name: 'Checks of batch 1', exact: true }).getByRole('listitem')).toHaveCount(3)
  w.look() // the latest result of each kind and the history
  await w.click(w.page.getByRole('button', { name: 'Release' }))
  const dialog = w.page.getByRole('dialog', { name: 'Release batch 1' })
  await w.keys('Identity, purity and viability after preservation passed.')
  await w.click(dialog.getByRole('button', { name: 'Release batch' }))
  await expect(w.page.getByRole('heading', { level: 3, name: 'Batch 1: Released' })).toBeFocused()
  await w.shot('released')
  w.note('The reason is typed although the checks already say it')
  await w.done()
})

test('C9 answer a request: may the strain go out for commercial research, then send it', async ({ browser }, info) => {
  // seed_dev holds the request: Example Institute of Microbiology asks for BAC 29 (soil isolate
  // DEP-1) for commercial research, which the depositor's terms allow only on request.
  const w = await Walk.as(browser, info, 'bac-curator', curator('C9', 'Answer a request for commercial research and send vials'))
  await w.start()
  await openLab(w, LAB)
  await w.click(w.page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Requests' }))
  const row = w.page.getByRole('table', { name: 'Requests' }).getByRole('row', { name: /Commercial research/ }).first()
  await w.read(row)
  await w.click(row.getByRole('link').first())
  const manager = w.page.getByRole('list', { name: 'Needs a manager’s approval' })
  await expect(manager).toContainText('only on request to the depositor')
  await w.read(manager)
  await expect(w.page.getByText('A manager approves this request.')).toBeVisible()
  w.impossible('The curator may only reject it or wait: the use is on request to the depositor, so a manager approves, and nothing records the depositor\'s answer but the reason. Sending is part B', '#18')
  await w.done()
})

test('C11 record a request that came by e-mail, with the signed MTA', async ({ browser }, info) => {
  const name = `Bacillus subtilis supply ${RUN}`
  const setup = await setupAs(browser, 'bac-curator')
  const lab = await labId(setup.page, LAB)
  const strain = await supplyStrain(setup.page, lab, name, 'Bacillus subtilis')
  const made = await batchOf(setup.page, lab, strain.passage, 4)
  await setup.close()
  const bench = await setupAs(browser, 'bac-technician')
  await passAll(bench.page, lab, made.id, made.vials[0]?.id ?? '')
  await bench.close()
  const releaser = await setupAs(browser, 'bac-curator')
  await release(releaser.page, lab, made.id)
  await releaser.close()

  const w = await Walk.as(browser, info, 'bac-curator', curator('C11', 'Record a request that came by e-mail, with the signed MTA'))
  await w.start()
  // Home's quick action (#69), where the lab picker, the lab and its Requests tab led before.
  await w.click(w.page.getByRole('region', { name: 'Quick actions' }).getByRole('link', { name: 'Enter a request' }))
  const form = w.page.getByRole('form', { name: 'New request' })
  await w.choose(form.getByRole('combobox', { name: 'Requester' }), /Example Institute of Microbiology/)
  await w.choose(form.getByRole('combobox', { name: 'Use' }), 'Teaching')
  await w.type(form.getByRole('textbox', { name: 'End use' }), 'Practical classes in microbiology.')
  await w.choose(form.getByRole('combobox', { name: 'Declared containment level' }), '1')
  await w.type(form.getByRole('combobox', { name: 'Strain 1' }), strain.number)
  await w.click(w.page.getByRole('option', { name: new RegExp(`^${strain.number},`) }))
  // The field holds 1 already: typed into, 2 becomes 12. The person selects it first.
  await w.click(form.getByRole('textbox', { name: 'Vials of strain 1' }))
  await w.press('Control+a')
  await w.keys('2')
  await w.click(form.getByRole('button', { name: 'Enter the request' }))
  await expect(w.page.getByRole('heading', { level: 1, name: /^Request \d{4}\/\d+$/ })).toBeVisible()
  await w.read(w.page.getByRole('list', { name: 'Blocks the approval' }))
  await w.click(w.page.getByRole('button', { name: 'Record an acceptance' }))
  const dialog = w.page.getByRole('dialog', { name: 'Record an acceptance of the MTA' })
  await w.type(dialog.getByRole('textbox', { name: 'Signed by' }), 'Petra Ukázková')
  await w.choose(dialog.getByRole('combobox', { name: "Signer's role" }), 'Responsible scientist')
  await w.click(dialog.getByRole('checkbox', { name: 'The signer may bind the institution' }))
  const chooser = w.page.waitForEvent('filechooser')
  await w.click(dialog.getByLabel('Signed copy'))
  await (await chooser).setFiles({ name: 'signed-mta.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\n% walkthrough\n') })
  await w.click(dialog.getByRole('button', { name: 'Record the acceptance' }))
  await expect(w.page.getByText('Nothing stands in the way: a curator may approve it.')).toBeVisible()
  await w.shot('entered')
  w.note('The signed copy is chosen in the file picker of the system, a step a person also needs to find the file (counted as one click)')
  w.note('The vials field already holds 1: typing 2 into it gives 12, and the request then says 12 vials are asked for. The person must select the 1 first')
  await w.done()
})

test('C10 deaccession a strain that no longer grows', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-curator', curator('C10', 'Deaccession a strain that no longer grows'))
  await w.start()
  await openStrains(w, LAB)
  await findStrain(w, 'BAC 14', /^BAC 14 /)
  w.look()
  await expect(w.page.getByRole('button', { name: /Deaccession/ })).toHaveCount(0)
  w.impossible('No deaccession: the strain list filters by "Deaccessioned" but no screen sets it', '#20')
  await w.done()
})
