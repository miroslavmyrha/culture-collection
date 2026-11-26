import { type Browser, expect, type Page, test } from '@playwright/test'
import { accountButton, axe, password, signedInAs, signOut, watchCsp } from './support.js'

// The second factor with a security key (#176), against the real API. First the two managers of
// E2E other lab reset e2e-key (one proposes, the other confirms and gets the enrolment code), so
// the spec runs again without a new seed and walks the recovery of a lost key too. Then e2e-key
// signs in, enters the code, enrols a key and sees the recovery codes once, and the next sign-in
// uses the key. Chrome's virtual authenticator (CDP WebAuthn domain) plays the hardware key. Not
// through the production proxy: Chrome refuses WebAuthn on a page whose certificate it does not
// trust, and the production e2e runs with a self-signed one.
const USER = 'e2e-key'
const OTHER_LAB = 'E2O'

async function as(browser: Browser, user: string) {
  const context = await browser.newContext({ storageState: signedInAs(user) })
  const page = await context.newPage()
  await page.goto('/')
  return { page, close: () => context.close() }
}

/** A JSON read or write with the session and its CSRF token, from the page's origin; fails loudly. */
async function call<T>(page: Page, url: string, payload?: unknown): Promise<T> {
  return page.evaluate(
    async ({ where, sent }) => {
      await fetch('/api/v1/auth/csrf/')
      const token = decodeURIComponent(/(?:^|; )(?:__Host-)?csrftoken=([^;]+)/.exec(document.cookie)?.[1] ?? '')
      const init =
        sent === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token }, body: JSON.stringify(sent) }
      const response = await fetch(where, init)
      if (!response.ok) throw new Error(`${where}: ${response.status} ${await response.text()}`)
      return response.json()
    },
    { where: url, sent: payload },
  )
}

/** Two managers reset e2e-key; the confirmation hands over its enrolment code. */
async function freshEnrolmentCode(browser: Browser): Promise<string> {
  const manager = await as(browser, 'e2e-other-manager')
  const deputy = await as(browser, 'e2e-other-deputy')
  try {
    const labs = await call<{ results: { public_id: string; code: string }[] }>(manager.page, '/api/v1/labs/?limit=200')
    const lab = labs.results.find((l) => l.code === OTHER_LAB)?.public_id ?? ''
    const members = await call<{ results: { public_id: string; username: string }[] }>(manager.page, `/api/v1/labs/${lab}/members/?limit=200`)
    const member = members.results.find((m) => m.username === USER)?.public_id ?? ''
    const reset = await call<{ public_id: string }>(manager.page, '/api/v1/auth/factor-resets/propose/', {
      member,
      reason: 'e2e: the virtual key of the last run is gone',
    })
    const confirmed = await call<{ enrolment_code: string | null }>(deputy.page, `/api/v1/auth/factor-resets/${reset.public_id}/confirm/`, {
      reason: 'e2e: checked by the second manager',
    })
    expect(confirmed.enrolment_code).toBeTruthy()
    return confirmed.enrolment_code ?? ''
  } finally {
    await manager.close()
    await deputy.close()
  }
}

test.skip(process.env.E2E_BASE_URL !== undefined, 'WebAuthn needs a trusted certificate: the production e2e has a self-signed one')

test('a user without a factor enrols a security key at the sign-in, then signs in with it', async ({ browser, page }) => {
  const enrolmentCode = await freshEnrolmentCode(browser)
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
  // The one-time code the confirming manager was handed (#176).
  await page.getByRole('textbox', { name: 'Enrolment code' }).fill(enrolmentCode)
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
