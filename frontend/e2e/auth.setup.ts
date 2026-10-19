import { expect, test as setup } from '@playwright/test'
import { password, signedInAs, signedInUsers } from './support.js'

// One sign-in per user for the whole run (see signedInUsers in support.ts).
for (const user of signedInUsers) {
  setup(`sign in ${user}`, async ({ page }) => {
    await page.goto('/login')
    await page.getByLabel('Username').fill(user)
    await page.getByLabel('Password').fill(password)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Home' })).toBeVisible()
    await page.context().storageState({ path: signedInAs(user) })
  })
}
