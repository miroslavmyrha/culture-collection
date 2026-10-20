import { type Page, expect, test } from '@playwright/test'
import { RUN, Walk, api, field, labId, openLab, rows, setupAs } from './walk.js'

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
  await openLab(w, BAC)
  w.look()
  await w.click(w.page.getByRole('navigation', { name: 'Lab sections' }).getByRole('link', { name: 'Strains' }))
  await expect(w.page.getByText(/^1 to 25 of \d+$/)).toBeVisible()
  w.look()
  w.impossible('No figures: the strain count is only the pager line, and vials, batches waiting or free places have no count anywhere')
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
