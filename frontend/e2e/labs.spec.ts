import { expect, type Page, test } from '@playwright/test'
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
  const own = page.getByRole('dialog', { name: `Remove ${username}?` })
  await own.getByRole('button', { name: 'Remove' }).click()
  await expect(own.getByRole('alert')).toHaveText('A lab needs at least one manager. Make another member manager first.')
  await own.getByRole('button', { name: 'Cancel' }).click()

  // Remove after a confirmation
  await page.getByRole('button', { name: 'Remove e2e-colleague' }).click()
  const confirm = page.getByRole('dialog', { name: 'Remove e2e-colleague?' })
  await expect(confirm.getByRole('button', { name: 'Cancel' })).toBeFocused()
  await confirm.getByRole('button', { name: 'Remove' }).click()
  await expect(confirm).toBeHidden()
  await expect(members.getByRole('row', { name: /e2e-colleague/ })).toHaveCount(0)

  expect(violations()).toEqual([])
})
