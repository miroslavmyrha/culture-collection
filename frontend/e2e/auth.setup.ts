import { test as setup } from '@playwright/test'
import { password, signIn, signedInUsers } from './support.js'

// One sign-in per user for the whole run (see signedInUsers in support.ts).
for (const user of signedInUsers) {
  setup(`sign in ${user}`, async ({ page }) => {
    await signIn(page, user, password)
  })
}
