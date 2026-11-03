import { type Browser, expect, type Page, test } from '@playwright/test'
import { axe, signedInAs, username, watchCsp } from './support.js'

// #167, act 281/2002 Sb., § 14a(4): the lab keeps the list of the people with access to its highly
// risky agents. The manager (e2e-user) puts e2e-technician on the list, prints it, and takes them
// off again; e2e-viewer sees none of it. seed_e2e gives E2E lab one VRAT permit that ended in
// 2025, so the printed list says no permit is in force. Only e2e-technician's entries change, and
// a11y.spec.ts reads the list filtered to its own user, so the two may run side by side.

const RUN = Date.now().toString(36)
const PERSON = 'e2e-technician'

async function as(browser: Browser, user: string) {
  const context = await browser.newContext({ storageState: signedInAs(user), viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  return { page, close: () => context.close() }
}

async function openLab(page: Page) {
  await page.goto('/labs')
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeVisible()
}

/** A run that failed half way may have left the person on the list: end that entry first. */
async function offTheList(page: Page, person: string) {
  await page.evaluate(async (who) => {
    await fetch('/api/v1/auth/csrf/')
    const token = decodeURIComponent(/(?:^|; )csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? '')
    const lab = location.pathname.split('/')[2] ?? ''
    const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': token }
    const entries: { public_id: string; username: string; ended_at: string | null }[] = await (await fetch(`/api/v1/labs/${lab}/vrat-access/`, { headers })).json()
    for (const entry of entries.filter((e) => e.username === who && e.ended_at === null)) {
      const response = await fetch(`/api/v1/labs/${lab}/vrat-access/${entry.public_id}/end/`, { method: 'POST', headers, body: JSON.stringify({ reason: 'Reset before an end to end run.' }) })
      if (!response.ok) throw new Error(`end: ${response.status}`)
    }
  }, person)
}

test('a manager puts a member on the VRAT access list, prints it for SÚJB and takes them off; a viewer sees none of it', async ({ browser }) => {
  const manager = await as(browser, username)
  const page = manager.page
  const violations = await watchCsp(page)
  await openLab(page)
  await offTheList(page, PERSON)
  await page.reload()
  const section = page.getByRole('region', { name: 'VRAT access list' })
  await expect(section.getByRole('heading', { level: 2, name: 'VRAT access list' })).toBeVisible()

  const form = section.getByRole('form', { name: 'Put a member on the VRAT access list' })
  // A user who is not a member of the lab is refused on the field.
  await form.getByRole('textbox', { name: 'Username' }).fill('e2e-outsider')
  await form.getByRole('textbox', { name: 'Reason' }).fill(`Works in the BSL-3 suite (${RUN}).`)
  await form.getByRole('button', { name: 'Put on the list' }).click()
  await expect(form.getByRole('textbox', { name: 'Username' })).toHaveAccessibleDescription('An active member of this lab No active member of this lab has this username')
  await form.getByRole('textbox', { name: 'Username' }).fill(PERSON)
  await form.getByRole('button', { name: 'Put on the list' }).click()
  await expect(form.getByText(`Put ${PERSON} on the VRAT access list.`)).toBeVisible()
  const current = section.getByRole('table', { name: 'People with VRAT access' })
  const row = current.getByRole('row', { name: new RegExp(`^${PERSON} `) })
  await expect(row).toContainText(`Works in the BSL-3 suite (${RUN}).`)
  await expect(row).toContainText(username)
  expect(await axe(page, 'main')).toEqual([])

  // The printable list: the lab, no permit in force, the person with access, printed today.
  await section.getByRole('link', { name: 'Print the VRAT access list' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'VRAT access list of E2E lab' })).toBeFocused()
  await expect(page).toHaveTitle('VRAT access list of E2E lab | Culture collection')
  const facts = page.locator('main dl')
  await expect(facts).toContainText('E2E lab (E2E)')
  await expect(facts).toContainText('None in force on record')
  await expect(facts).toContainText(`Printed on${new Date().toLocaleDateString('sv')}`)
  const printed = page.getByRole('table', { name: 'VRAT access list', exact: true }).getByRole('row', { name: new RegExp(`Works in the BSL-3 suite \\(${RUN}\\)`) })
  await expect(printed).toContainText('has access')
  expect(await axe(page, 'main')).toEqual([])
  // On paper only the list: no top bar, no lab tabs, no buttons or back link.
  await page.emulateMedia({ media: 'print' })
  await expect(page.getByRole('banner')).toBeHidden()
  await expect(page.getByRole('navigation', { name: 'Lab sections' })).toBeHidden()
  await expect(page.getByRole('button', { name: 'Print' })).toBeHidden()
  await expect(page.getByRole('link', { name: 'Back to E2E lab' })).toBeHidden()
  await expect(printed).toBeVisible()
  await page.emulateMedia({ media: 'screen' })

  // Off the list with a reason: the entry moves to the ended ones and stays in the history.
  await page.getByRole('link', { name: 'Back to E2E lab' }).click()
  await section.getByRole('button', { name: `End VRAT access of ${PERSON}` }).click()
  const dialog = page.getByRole('dialog', { name: `End VRAT access of ${PERSON}` })
  await dialog.getByRole('textbox', { name: 'Reason' }).fill(`Moved to another project (${RUN}).`)
  await dialog.getByRole('button', { name: 'End access' }).click()
  await expect(dialog).toBeHidden()
  await expect(current.getByRole('row', { name: new RegExp(`^${PERSON} `) })).toHaveCount(0)
  const ended = section.getByRole('table', { name: 'Ended entries of the VRAT access list' }).getByRole('row', { name: new RegExp(`Moved to another project \\(${RUN}\\)`) })
  await expect(ended).toContainText(PERSON)
  await expect(ended).toContainText(username)
  expect(violations()).toEqual([])
  await manager.close()

  const viewer = await as(browser, 'e2e-viewer')
  await openLab(viewer.page)
  await expect(viewer.page.getByRole('table', { name: 'Members' })).toBeVisible()
  await expect(viewer.page.getByRole('heading', { name: 'VRAT access list' })).toHaveCount(0)
  await viewer.page.goto(`${new URL(viewer.page.url()).pathname}/vrat-access`)
  await expect(viewer.page.getByText('Only managers see the VRAT access list.')).toBeVisible()
  await expect(viewer.page.getByRole('table')).toHaveCount(0)
  await viewer.close()
})
