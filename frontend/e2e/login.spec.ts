import { expect, type Page, test } from '@playwright/test'
import { accountButton, formUser, labPicker, password, secondFactor, signOut, watchCsp } from './support.js'

/** The CSP header as a map of directive to sources. */
function parseCsp(header: string): Record<string, string[]> {
  return Object.fromEntries(
    header.split(';').map((directive) => {
      const [name = '', ...values] = directive.trim().split(/\s+/)
      return [name, values]
    }),
  )
}

/** knowndevice in development, __Host-knowndevice in production. */
async function knownDeviceCookie(page: Page) {
  return (await page.context().cookies()).find((cookie) => cookie.name.endsWith('knowndevice'))
}

async function signIn(page: Page, pass = password) {
  await page.getByLabel('Username').fill(formUser)
  await page.getByLabel('Password').fill(pass)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

test('signs in through the real API under the production CSP and returns to the deep link', async ({ page }) => {
  const violations = await watchCsp(page)

  await page.goto('/?tab=b')
  await expect(page).toHaveURL('/login?redirect=%2F%3Ftab%3Db')
  await signIn(page)
  // The password signs nobody in (#176): the second factor first.
  await expect(page.getByRole('heading', { name: 'Confirm it is you' })).toBeVisible()
  await secondFactor(page)
  await expect(accountButton(page, formUser)).toBeVisible()
  await expect(page).toHaveURL('/?tab=b')

  // The session survives a reload: cookie based, nothing in localStorage.
  await page.reload()
  await expect(accountButton(page, formUser)).toBeVisible()
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([])
  // The login remembered this browser for the login limits: out of reach of scripts, no name in it.
  const device = await knownDeviceCookie(page)
  expect(device).toMatchObject({ httpOnly: true, sameSite: 'Lax', path: '/' })
  expect(device?.value).not.toContain(formUser)
  expect(await page.evaluate(() => document.cookie)).not.toContain('knowndevice')

  await signOut(page, formUser)
  await expect(page.getByRole('form', { name: 'Sign in' })).toBeVisible()
  await expect(page).toHaveURL('/login?signedOut=true')
  await expect(page.getByRole('status')).toHaveText('You have been signed out.')
  await expect(labPicker(page)).toHaveCount(0)
  await expect(accountButton(page)).toHaveCount(0)
  expect((await knownDeviceCookie(page))?.value).toBe(device?.value) // signing out keeps it

  await page.goto('/no-such-page')
  await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible()
  expect(violations()).toEqual([])
})

test('wrong password shows an error', async ({ page }) => {
  await page.goto('/login')
  await signIn(page, 'wrong password')
  await expect(page.getByRole('alert')).toHaveText('Invalid username or password.')
  await expect(page).toHaveURL('/login')
})

// `vite preview` sends the placeholder as the nonce; the production proxy (E2E_BASE_URL,
// deploy/e2e-production.sh, #178) puts a fresh random one in each response.
const PROXIED = process.env.E2E_BASE_URL !== undefined
const EXPECTED_NONCE = PROXIED ? /^[0-9a-f]{32}$/ : /^__CSP_NONCE__$/
// How CSS-in-JS reads the nonce: the property, because browsers hide the attribute.
const pageNonce = (page: Page) => page.evaluate(() => document.querySelector<HTMLMetaElement>('meta[property="csp-nonce"]')?.nonce ?? '')

test('sends exactly the production CSP, the security headers and the nonce of the page', async ({ page }) => {
  const response = await page.goto('/login')
  const headers = response?.headers() ?? {}
  const nonce = await pageNonce(page)
  expect(nonce).toMatch(EXPECTED_NONCE)
  // A reviewed security contract, not a snapshot: every relaxation (unsafe-eval, unsafe-inline,
  // a default Trusted Types policy, a new host) has to change this map in review.
  expect(parseCsp(headers['content-security-policy'] ?? '')).toEqual({
    'default-src': ["'self'"],
    'script-src': ["'self'"],
    'style-src': ["'self'", `'nonce-${nonce}'`],
    'img-src': ["'self'", 'data:'],
    'font-src': ["'self'"],
    'connect-src': ["'self'"],
    'worker-src': ["'self'"],
    'frame-src': ["'none'"],
    'object-src': ["'none'"],
    'base-uri': ["'none'"],
    'frame-ancestors': ["'none'"],
    'form-action': ["'self'"],
    'require-trusted-types-for': ["'script'"],
    'trusted-types': ["'none'"],
  })
  expect(headers).toMatchObject({
    'referrer-policy': 'strict-origin-when-cross-origin',
    'cross-origin-opener-policy': 'same-origin',
    'x-frame-options': 'DENY',
    'x-content-type-options': 'nosniff',
  })
  expect(headers['permissions-policy']).toContain('camera=()')
  // Behind the proxy each response has its own nonce.
  await page.reload()
  if (PROXIED) expect(await pageNonce(page)).not.toBe(nonce)
})

test('enforces Trusted Types, and no policy may be created', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('form', { name: 'Sign in' })).toBeVisible()
  const result = await page.evaluate(() => {
    // Inside evaluate on purpose: this function runs in the browser.
    // oxlint-disable-next-line unicorn/consistent-function-scoping -- the helper must live inside evaluate: only its body is sent to the browser
    const attempt = (fn: () => void) => {
      try {
        fn()
        return 'allowed'
      } catch (error) {
        return error instanceof Error ? error.message : String(error)
      }
    }
    const tt = window.trustedTypes
    return {
      rawHtml: attempt(() => {
        document.body.insertAdjacentHTML('beforeend', '<b>raw</b>')
      }),
      // The name the CSP allowed before #238, and any other: neither may be created now.
      dompurify: attempt(() => tt?.createPolicy('dompurify', {})),
      policy: attempt(() => tt?.createPolicy('any', {})),
    }
  })
  expect(result.rawHtml).toMatch(/TrustedHTML/)
  expect(result.dompurify).toMatch(/disallowed/)
  expect(result.policy).toMatch(/disallowed/)
})

test('MUI styles apply under the production CSP: every emotion style carries the nonce', async ({ page }) => {
  const violations = await watchCsp(page)
  await page.goto('/login')
  const bar = page.getByRole('banner')
  await expect(bar).toContainText('Culture Collection')
  // Without the nonce the CSP blocks emotion's <style> and the bar keeps a transparent background.
  expect(await bar.evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)')
  const styles = await page.evaluate(() => {
    const nonce = document.querySelector<HTMLMetaElement>('meta[property="csp-nonce"]')?.nonce
    const emotion = [...document.querySelectorAll<HTMLStyleElement>('style[data-emotion]')]
    return { nonce, count: emotion.length, withNonce: emotion.filter((style) => style.nonce === nonce).length }
  })
  expect(styles.nonce).toMatch(EXPECTED_NONCE)
  expect(styles.count).toBeGreaterThan(0)
  expect(styles.withNonce).toBe(styles.count)
  expect(violations()).toEqual([])
})
