import { type Page, expect, test } from '@playwright/test'
import { RUN, Walk, api, batchOf, field, labId, openLab, openWaiting, passAll, release, requestFor, rows, setupAs, supplyStrain } from './walk.js'

// A manager of Bacteriology and of Regulated agents (seed_dev): people, rights and the lab's
// legal texts. dev-no-lab is a user in no lab, reg-technician works in Regulated agents.
const BAC = 'Bacteriology'
const REG = 'Regulated agents'
const COLLEAGUE = 'dev-no-lab'
const manager = (id: string, task: string) => ({ id, role: 'manager' as const, task })

/** Puts the colleague into the lab with the role, or out of it (null), before a task. */
async function membership(page: Page, lab: string, username: string, role: string | null) {
  const member = rows(await api(page, lab, 'members/?limit=200')).find((m) => m.username === username)
  if (member !== undefined) await api(page, lab, `members/${field(member, 'public_id')}/`, undefined, 'DELETE')
  if (role !== null) await api(page, lab, 'members/', { username, role })
}

/** Gives or takes the location grant of a member of Regulated agents, before a task. */
async function grant(page: Page, lab: string, username: string, open: boolean) {
  const current = rows(await api(page, lab, 'location-grants/')).find((g) => g.username === username)
  if (current !== undefined) await api(page, lab, `location-grants/${field(current, 'public_id')}/revoke/`, { reason: 'Reset before a walkthrough.' })
  if (!open) return
  const member = rows(await api(page, lab, 'members/?limit=200')).find((m) => m.username === username)
  await api(page, lab, 'location-grants/', { member: field(member, 'public_id'), reason: 'Set up before a walkthrough.' })
}

async function prepare(browser: Parameters<typeof setupAs>[0], user: 'bac-manager' | 'reg-manager', lab: string, step: (page: Page, lab: string) => Promise<void>) {
  const setup = await setupAs(browser, user)
  await step(setup.page, await labId(setup.page, lab))
  await setup.close()
}

test('M1 add a new colleague as a technician', async ({ browser }, info) => {
  await prepare(browser, 'bac-manager', BAC, (page, lab) => membership(page, lab, COLLEAGUE, null))
  const w = await Walk.as(browser, info, 'bac-manager', manager('M1', 'Add a new colleague as a technician'))
  await w.start()
  await openLab(w, BAC)
  const form = w.page.getByRole('form', { name: 'Add a member' })
  await w.type(form.getByRole('textbox', { name: 'Username' }), COLLEAGUE)
  await w.choose(form.getByRole('combobox', { name: 'Role', exact: true }), 'Technician')
  await w.click(form.getByRole('button', { name: 'Add member' }))
  await expect(w.page.getByRole('table', { name: 'Members' }).getByRole('row', { name: new RegExp(`^${COLLEAGUE} .*Technician`) })).toBeVisible()
  w.note('The username must be known exactly: there is no search of users, and a new person needs an account from an administrator first')
  await w.done()
})

test('M2 promote a technician to curator', async ({ browser }, info) => {
  await prepare(browser, 'bac-manager', BAC, (page, lab) => membership(page, lab, COLLEAGUE, 'technician'))
  const w = await Walk.as(browser, info, 'bac-manager', manager('M2', 'Promote a technician to curator'))
  await w.start()
  await openLab(w, BAC)
  await w.click(w.page.getByRole('button', { name: `Change role of ${COLLEAGUE}` }))
  const dialog = w.page.getByRole('dialog', { name: `Change the role of ${COLLEAGUE}` })
  await w.choose(dialog.getByRole('combobox', { name: 'Role', exact: true }), 'Curator')
  await w.click(dialog.getByRole('button', { name: 'Save role' }))
  await expect(w.page.getByRole('table', { name: 'Members' }).getByRole('row', { name: new RegExp(`^${COLLEAGUE} .*Curator`) })).toBeVisible()
  await w.done()
})

test('M3 remove a member who left', async ({ browser }, info) => {
  await prepare(browser, 'bac-manager', BAC, (page, lab) => membership(page, lab, COLLEAGUE, 'technician'))
  const w = await Walk.as(browser, info, 'bac-manager', manager('M3', 'Remove a member who left'))
  await w.start()
  await openLab(w, BAC)
  await w.click(w.page.getByRole('button', { name: `Remove ${COLLEAGUE}` }))
  await w.click(w.page.getByRole('alertdialog', { name: `Remove ${COLLEAGUE}?` }).getByRole('button', { name: 'Remove' }))
  await expect(w.page.getByRole('table', { name: 'Members' }).getByRole('row', { name: new RegExp(`^${COLLEAGUE} `) })).toHaveCount(0)
  await w.done()
})

test('M4 grant a colleague the right to see regulated locations', async ({ browser }, info) => {
  await prepare(browser, 'reg-manager', REG, (page, lab) => grant(page, lab, 'reg-technician', false))
  const w = await Walk.as(browser, info, 'reg-manager', manager('M4', 'Grant a colleague the regulated location right'))
  await w.start()
  await openLab(w, REG)
  await w.click(w.page.getByRole('button', { name: 'Grant regulated locations for reg-technician' }))
  const dialog = w.page.getByRole('dialog', { name: 'Let reg-technician see regulated locations' })
  await w.type(dialog.getByRole('textbox', { name: 'Reason' }), `Takes over the inventory of the locked freezer (${RUN}).`)
  await w.click(dialog.getByRole('button', { name: 'Grant' }))
  await expect(w.page.getByRole('row', { name: /^reg-technician / })).toContainText('May see')
  await w.done()
})

test('M5 revoke the regulated location right', async ({ browser }, info) => {
  await prepare(browser, 'reg-manager', REG, (page, lab) => grant(page, lab, 'reg-technician', true))
  const w = await Walk.as(browser, info, 'reg-manager', manager('M5', 'Revoke the regulated location right'))
  await w.start()
  await openLab(w, REG)
  await w.click(w.page.getByRole('button', { name: 'Revoke regulated locations for reg-technician' }))
  const dialog = w.page.getByRole('dialog', { name: /reg-technician/ })
  await w.type(dialog.getByRole('textbox', { name: 'Reason' }), 'The inventory is finished.')
  await w.click(dialog.getByRole('button', { name: 'Revoke' }))
  await expect(w.page.getByRole('row', { name: /^reg-technician / })).toContainText('Hidden')
  await w.done()
})

test('M6 publish a new version of the MTA', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-manager', manager('M6', 'Publish a new version of the standard MTA'))
  await w.start()
  await openLab(w, BAC)
  await w.click(w.page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'MTA templates' }))
  w.look()
  await w.click(w.page.getByRole('table', { name: 'MTA templates' }).getByRole('link').first())
  await w.click(w.page.getByRole('link', { name: /^Publish a new version of STD/ }))
  const form = w.page.getByRole('form', { name: 'Publish an MTA version' })
  const text = form.getByRole('textbox', { name: 'Text' })
  await expect(text).not.toHaveValue('')
  await w.click(text)
  await w.press('Control+End')
  await w.keys(`\n\nClause 9 (invented example, ${RUN}): the recipient names the collection in publications.`)
  await w.click(form.getByRole('button', { name: 'Publish the version' }))
  await expect(w.page.getByRole('heading', { level: 1, name: /^STD version \d+/ })).toBeVisible()
  await w.done()
})

test('M7 see how the lab stands: strains, vials, batches waiting', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'bac-manager', manager('M7', 'See how the lab stands (strains, vials, batches waiting)'))
  await w.start()
  // The lab's card on Home (#69): strains, batches by status, vials available, free places, open requests.
  const card = w.page.getByRole('region', { name: 'My labs' }).getByRole('article', { name: BAC })
  await w.read(card)
  await expect(card.getByRole('link', { name: /^Strains: \d+$/ })).toBeVisible()
  await expect(card).toContainText('Vials available')
  await expect(card).toContainText('Free box positions')
  w.look()
  await w.shot('lab-card')
  w.note('The figures are of today: no trend, and nothing says how many vials of each strain are left')
  await w.done()
})

test('M8 review who revealed regulated locations this month', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'reg-manager', manager('M8', 'Review who revealed regulated locations this month'))
  await w.start()
  await openLab(w, REG)
  w.look()
  await expect(w.page.getByRole('link', { name: /reveal|audit|history/i })).toHaveCount(0)
  w.impossible('Every reveal is recorded, but no screen shows the record: only a database query does')
  await w.done()
})

test('M9 check the lab\'s permits and when they expire', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'reg-manager', manager('M9', 'Check the lab\'s permits and when they expire'))
  await w.start()
  await openLab(w, REG)
  w.look()
  await expect(w.page.getByRole('link', { name: /permit/i })).toHaveCount(0)
  w.impossible('Permits gate every acceptance of a regulated strain, but no screen lists them or their expiry: only the Django admin')
  await w.done()
})

test('M10 review who has access to the regulated lab and what they may see', async ({ browser }, info) => {
  const w = await Walk.as(browser, info, 'reg-manager', manager('M10', 'Review who has access to the regulated lab'))
  await w.start()
  await openLab(w, REG)
  await w.read(w.page.getByRole('table', { name: 'Members' }))
  await expect(w.page.getByRole('columnheader', { name: 'Regulated locations' })).toBeVisible()
  w.note('Names are empty for every seeded member: the table shows usernames only')
  await w.done()
})

test('M11 approve a request for a regulated strain', async ({ browser }, info) => {
  // A strain of an invented taxon with a dual-use restriction, released stock, and a request of
  // the seeded requester with its MTA accepted: only a manager may approve it.
  const setup = await setupAs(browser, 'bac-curator')
  const lab = await labId(setup.page, BAC)
  const strain = await supplyStrain(setup.page, lab, `Testella cerea supply ${RUN}`, 'Testella cerea', [{ kind: 'dual_use', reference: '1C351.c', act: '(EU) 2025/2003' }])
  const made = await batchOf(setup.page, lab, strain.passage, 4)
  await setup.close()
  const bench = await setupAs(browser, 'bac-technician')
  await passAll(bench.page, lab, made.id, made.vials[0]?.id ?? '')
  await bench.close()
  const curator = await setupAs(browser, 'bac-curator')
  await release(curator.page, lab, made.id)
  const request = await requestFor(curator.page, lab, strain.id, 2, `Growth curves, walkthrough ${RUN}.`)
  await curator.close()

  const w = await Walk.as(browser, info, 'bac-manager', manager('M11', 'Approve a request for a regulated strain'))
  await w.start()
  // The request waits on Home, flagged for a manager (#69).
  await openWaiting(w, 'Requests to decide', `Request ${request.number}, Example Institute of Microbiology`)
  await w.read(w.page.getByRole('list', { name: 'Needs a manager’s approval' }))
  await w.click(w.page.getByRole('button', { name: 'Approve and reserve the vials' }))
  await w.keys('Dual-use inside the EU: no licence is needed for the transfer.')
  await w.click(w.page.getByRole('dialog').getByRole('button', { name: 'Approve and reserve' }))
  const reserved = w.page.getByRole('table', { name: 'Strains' }).getByRole('row').nth(1).getByRole('cell').nth(4)
  await expect(reserved).toHaveText(new RegExp(`^${strain.number} / 1 / \\d+; ${strain.number} / 1 / \\d+$`))
  w.look()
  await w.shot('approved')
  w.note('The finding says that the strain is regulated, not which permits were checked: the reason repeats what the manager looked up elsewhere')
  await w.done()
})
