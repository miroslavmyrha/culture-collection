import { AxeBuilder } from '@axe-core/playwright'
import { expect, type Locator, type Page, test } from '@playwright/test'
import { password, username, watchCsp } from './support.js'

async function signIn(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText(`Signed in as ${username}`)).toBeVisible()
}

// Needs the seed: `python manage.py seed_e2e` (the CI workflow runs it before the tests).
// The test ends where it started (the colleague in no lab), so it can run again; after a failed
// run, seed again. One sign-in per test: the login throttle allows 10 a minute per client.
test('a manager sees their lab and role, then adds, changes and removes a member under the production CSP', async ({ page }) => {
  const violations = await watchCsp(page)
  await signIn(page)

  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Labs' }).click()
  await expect(page).toHaveURL('/labs')
  await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Labs' })).toHaveAttribute('aria-current', 'page')
  const row = page.getByRole('row', { name: /E2E lab/ })
  await expect(row).toContainText('E2E')
  await expect(row).toContainText('Manager')

  await row.getByRole('link', { name: 'E2E lab' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeVisible()
  await expect(page.getByText('Your role: Manager.')).toBeVisible()
  const members = page.getByRole('table', { name: 'Members' })
  await expect(members.getByRole('cell', { name: username, exact: true })).toBeVisible()

  // An unknown username is refused on its field
  const form = page.getByRole('form', { name: 'Add a member' })
  const field = form.getByRole('textbox', { name: 'Username' })
  await field.fill('nobody-here')
  await form.getByRole('button', { name: 'Add member' }).click()
  await expect(field).toHaveAttribute('aria-invalid', 'true')
  await expect(field).toHaveAccessibleDescription('An existing, active user Invalid user.')
  await expect(field).toBeFocused()

  // Add
  await form.getByLabel('Username').fill('e2e-colleague')
  await form.getByRole('combobox', { name: 'Role', exact: true }).selectOption('technician')
  await form.getByRole('button', { name: 'Add member' }).click()
  await expect(page.getByText('Added e2e-colleague.')).toBeVisible()
  const colleague = members.getByRole('row', { name: /e2e-colleague/ })
  await expect(colleague).toContainText('Technician')

  // Change the role in a dialog
  await page.getByRole('button', { name: 'Change role of e2e-colleague' }).click()
  const roleDialog = page.getByRole('dialog', { name: 'Change the role of e2e-colleague' })
  await roleDialog.getByRole('combobox', { name: 'Role', exact: true }).selectOption('curator')
  await roleDialog.getByRole('button', { name: 'Save role' }).click()
  await expect(roleDialog).toBeHidden()
  await expect(colleague).toContainText('Curator')

  // The last manager stays
  await page.getByRole('button', { name: `Remove ${username}` }).click()
  const own = page.getByRole('alertdialog', { name: `Remove ${username}?` })
  await own.getByRole('button', { name: 'Remove' }).click()
  await expect(own.getByRole('alert')).toHaveText('A lab needs at least one active manager. Make another member manager first.')
  await own.getByRole('button', { name: 'Cancel' }).click()

  // Remove after a confirmation
  await page.getByRole('button', { name: 'Remove e2e-colleague' }).click()
  const confirm = page.getByRole('alertdialog', { name: 'Remove e2e-colleague?' })
  await expect(confirm.getByRole('button', { name: 'Cancel' })).toBeFocused()
  await confirm.getByRole('button', { name: 'Remove' }).click()
  await expect(confirm).toBeHidden()
  await expect(members.getByRole('row', { name: /e2e-colleague/ })).toHaveCount(0)

  expect(violations()).toEqual([])
})

/**
 * Axe on one part of the page, with the rules of WCAG 2.2 A and AA. It waits until no ancestor
 * is transparent: during MUI's fade-in axe cannot compute contrast and reports it as incomplete,
 * not as a violation, so a dialog checked too early passes with unreadable text.
 */
async function axe(page: Page, selector: string) {
  const target = page.locator(selector)
  await expect
    .poll(() =>
      target.evaluate((element) => {
        let opacity = 1
        for (let node: Element | null = element; node; node = node.parentElement) opacity *= Number(getComputedStyle(node).opacity)
        return opacity
      }),
    )
    .toBe(1)
  const results = await new AxeBuilder({ page }).include(selector).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze()
  return results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)
}

const channels = (css: string) => (css.match(/[\d.]+/g) ?? []).map(Number)
const linear = (c: number) => (c / 255 <= 0.04045 ? c / 255 / 12.92 : ((c / 255 + 0.055) / 1.055) ** 2.4)
const luminance = ([r = 0, g = 0, b = 0]: number[]) => 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)

/**
 * The WCAG contrast of a text's colour (blended over its surface when translucent) against the
 * surface's background. axe leaves contrast inside an MUI dialog as "incomplete" ("could not be
 * determined because it partially overlaps other elements", axe-core 4.13.0), so the dialog's
 * text is measured here.
 */
async function contrast(text: Locator, surface: Locator) {
  const [fg = 0, fgG = 0, fgB = 0, alpha = 1] = channels(await text.evaluate((e) => getComputedStyle(e).color))
  const bg = channels(await surface.evaluate((e) => getComputedStyle(e).backgroundColor))
  const blended = [fg, fgG, fgB].map((c, i) => c * alpha + (bg[i] ?? 0) * (1 - alpha))
  const [light, dark] = [luminance(blended), luminance(bg)].toSorted((a, b) => b - a)
  return ((light ?? 0) + 0.05) / ((dark ?? 0) + 0.05)
}

// The removal below runs on the keyboard alone, against the real API. The request is held in
// the browser for a moment (page.route, then passed on unchanged) so the pending dialog can be
// checked: Escape must not close it, or a failure would be shown nowhere.
test('a manager removes a member with the keyboard only; the dialog passes axe and stays open while the request runs', async ({ page }) => {
  const violations = await watchCsp(page)
  await signIn(page)
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Labs' }).click()
  await page.getByRole('row', { name: /E2E lab/ }).getByRole('link', { name: 'E2E lab' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'E2E lab' })).toBeVisible()
  const form = page.getByRole('form', { name: 'Add a member' })
  await form.getByLabel('Username').fill('e2e-colleague')
  await form.getByRole('button', { name: 'Add member' }).click()
  const members = page.getByRole('table', { name: 'Members' })
  await expect(members.getByRole('row', { name: /e2e-colleague/ })).toHaveCount(1)

  // From here on only keys.
  const trigger = page.getByRole('button', { name: 'Remove e2e-colleague' })
  await page.getByRole('button', { name: 'Change role of e2e-colleague' }).focus()
  await page.keyboard.press('Tab')
  await expect(trigger).toBeFocused()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('alertdialog', { name: 'Remove e2e-colleague?' })
  await expect(dialog).toBeVisible()
  await expect(dialog).toHaveAccessibleDescription('e2e-colleague leaves E2E lab and loses access to it at once.')
  const cancel = dialog.getByRole('button', { name: 'Cancel' })
  const confirm = dialog.getByRole('button', { name: 'Remove' })
  await expect(cancel).toBeFocused()
  expect(await axe(page, '[role="alertdialog"]')).toEqual([])
  expect(await contrast(dialog.getByText('e2e-colleague leaves E2E lab'), dialog)).toBeGreaterThanOrEqual(4.5)
  expect(await contrast(cancel, dialog)).toBeGreaterThanOrEqual(4.5)
  expect(await contrast(confirm, confirm)).toBeGreaterThanOrEqual(4.5)

  // Escape closes while nothing runs, and the focus goes back to the row's button.
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()

  const gate: { open?: () => void } = {}
  const held = new Promise<void>((resolve) => {
    gate.open = resolve
  })
  await page.route('**/api/v1/labs/*/members/*/', async (route) => {
    if (route.request().method() === 'DELETE') await held
    await route.continue()
  })
  await page.keyboard.press('Enter')
  await expect(cancel).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(confirm).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(confirm).toHaveAttribute('aria-busy', 'true')
  await page.keyboard.press('Escape')
  await page.keyboard.press('Shift+Tab')
  await expect(cancel).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(dialog).toBeVisible()
  await expect(cancel).toHaveAttribute('aria-disabled', 'true')
  expect(await axe(page, '[role="alertdialog"]')).toEqual([])

  gate.open?.()
  await expect(dialog).toBeHidden()
  await expect(members.getByRole('row', { name: /e2e-colleague/ })).toHaveCount(0)
  expect(violations()).toEqual([])
})
