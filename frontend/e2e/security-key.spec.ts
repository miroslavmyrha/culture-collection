import { expect, test } from '@playwright/test'
import { accountButton, axe, password, signOut, watchCsp } from './support.js'

// The second factor with a security key (#176), against the real API. seed_e2e makes e2e-key
// without any factor and with a fresh enrolment code each run: its first sign-in enters the code and enrols a key and shows the recovery codes once,
// the next one signs in with the key. Chrome's virtual authenticator (CDP WebAuthn domain) plays
// the hardware key. Not through the production proxy: Chrome refuses WebAuthn on a page whose
// certificate it does not trust, and the production e2e runs with a self-signed one.
const USER = 'e2e-key'

test.skip(process.env.E2E_BASE_URL !== undefined, 'WebAuthn needs a trusted certificate: the production e2e has a self-signed one')

test('a user without a factor enrols a security key at the sign-in, then signs in with it', async ({ page }) => {
  const violations = await watchCsp(page)
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('WebAuthn.enable')
  await cdp.send('WebAuthn.addVirtualAuthenticator', {
    options: { protocol: 'ctap2', transport: 'usb', hasResidentKey: false, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true },
  })

  await page.goto('/login')
  await page.getByLabel('Username').fill(USER)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Add a second factor' })).toBeVisible()
  expect(await axe(page, 'main')).toEqual([])
  // The manager's one-time code first (#176): seed_e2e issues it each run.
  await page.getByRole('textbox', { name: 'Enrolment code' }).fill(process.env.E2E_ENROLMENT_CODE ?? 'e2eke-ycode')
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByLabel('Name of the key (optional)').fill('Virtual key')
  await page.getByRole('button', { name: 'Add a security key' }).click()

  const codes = page.getByRole('list', { name: 'Recovery codes' })
  await expect(codes.getByRole('listitem')).toHaveCount(10)
  expect(await axe(page, 'main')).toEqual([])
  await page.getByRole('button', { name: 'I have saved them, continue' }).click()
  await expect(accountButton(page, USER)).toBeVisible()

  await signOut(page, USER)
  await page.getByLabel('Username').fill(USER)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('button', { name: 'Use your security key' }).click()
  await expect(accountButton(page, USER)).toBeVisible()
  expect(violations()).toEqual([])
})
