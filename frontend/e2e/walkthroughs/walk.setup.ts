import { test as setup } from '@playwright/test'
import { signIn } from '../support.js'
import { DEV_USERS } from './walk.js'

// The walkthroughs work in the labs of `seed_dev` (Bacteriology, Regulated agents), as its
// users, with the password given to seed_dev. One sign-in per user and run, like auth.setup.ts.
const password = process.env.DEV_PASSWORD ?? ''

for (const user of DEV_USERS) {
  setup(`sign in ${user}`, async ({ page }) => {
    if (password === '') throw new Error('Set DEV_PASSWORD to the password given to seed_dev.')
    await signIn(page, user, password)
  })
}
