import { expect, type Page, test } from '@playwright/test'

const username = process.env.E2E_USERNAME ?? 'e2e-user'
const password = process.env.E2E_PASSWORD ?? 'e2e correct horse battery'

/**
 * Collects CSP and Trusted Types violations from every document the page loads: console errors
 * and securitypolicyviolation events. The binding sends each event to the test at once, so a
 * reload or goto does not drop what an earlier document reported (a window variable read at
 * the end only sees the last document). Chrome words Trusted Types errors as "requires
 * 'TrustedHTML' assignment", hence the wider pattern.
 */
async function watchCsp(page: Page) {
  const seen: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'error' && /Content Security Policy|Trusted ?(Type|HTML|Script)/i.test(msg.text())) seen.push(msg.text())
  })
  await page.exposeBinding('reportCspViolation', (_source, text: unknown) => {
    seen.push(String(text))
  })
  await page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (e) => {
      const report: unknown = Reflect.get(window, 'reportCspViolation')
      if (typeof report === 'function') void report(`${e.effectiveDirective} ${e.blockedURI}`)
    })
  })
  return () => seen
}

/** The CSP header as a map of directive to sources. */
function parseCsp(header: string): Record<string, string[]> {
  return Object.fromEntries(
    header.split(';').map((directive) => {
      const [name = '', ...values] = directive.trim().split(/\s+/)
      return [name, values]
    }),
  )
}

async function signIn(page: Page, pass = password) {
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password').fill(pass)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

test('signs in through the real API under the production CSP and returns to the deep link', async ({ page }) => {
  const violations = await watchCsp(page)

  await page.goto('/?tab=b')
  await expect(page).toHaveURL('/login?redirect=%2F%3Ftab%3Db')
  await signIn(page)
  await expect(page.getByText(`Signed in as ${username}`)).toBeVisible()
  await expect(page).toHaveURL('/?tab=b')

  // The session survives a reload: cookie based, nothing in localStorage.
  await page.reload()
  await expect(page.getByText(`Signed in as ${username}`)).toBeVisible()
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([])

  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('form', { name: 'Sign in' })).toBeVisible()
  await expect(page).toHaveURL('/login')

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

test('sends exactly the production CSP, the security headers and the nonce placeholder', async ({ page }) => {
  const response = await page.goto('/login')
  const headers = response?.headers() ?? {}
  // A reviewed security contract, not a snapshot: every relaxation (unsafe-eval, unsafe-inline,
  // a default Trusted Types policy, a new host) has to change this map in review.
  expect(parseCsp(headers['content-security-policy'] ?? '')).toEqual({
    'default-src': ["'self'"],
    'script-src': ["'self'"],
    'style-src': ["'self'", "'nonce-__CSP_NONCE__'"],
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
    'trusted-types': ['dompurify'],
  })
  expect(headers).toMatchObject({
    'referrer-policy': 'strict-origin-when-cross-origin',
    'cross-origin-opener-policy': 'same-origin',
    'x-frame-options': 'DENY',
    'x-content-type-options': 'nosniff',
  })
  expect(headers['permissions-policy']).toContain('camera=()')
  // How CSS-in-JS reads the nonce: the property, because browsers hide the attribute.
  const nonce = await page.evaluate(() => document.querySelector<HTMLMetaElement>('meta[property="csp-nonce"]')?.nonce)
  expect(nonce).toBe('__CSP_NONCE__')
})

test('enforces Trusted Types; the dompurify policy exists from boot', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('form', { name: 'Sign in' })).toBeVisible()
  const result = await page.evaluate(() => {
    // Inside evaluate on purpose: this function runs in the browser.
    // oxlint-disable-next-line unicorn/consistent-function-scoping
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
      duplicate: attempt(() => tt?.createPolicy('dompurify', {})),
      other: attempt(() => tt?.createPolicy('other', {})),
    }
  })
  expect(result.rawHtml).toMatch(/TrustedHTML/)
  expect(result.duplicate).toMatch(/already exists/)
  expect(result.other).toMatch(/disallowed/)
})

test('MUI styles apply under the production CSP: every emotion style carries the nonce', async ({ page }) => {
  const violations = await watchCsp(page)
  await page.goto('/login')
  const bar = page.getByRole('banner')
  await expect(bar).toContainText('Culture collection')
  // Without the nonce the CSP blocks emotion's <style> and the bar keeps a transparent background.
  expect(await bar.evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)')
  const styles = await page.evaluate(() => {
    const nonce = document.querySelector<HTMLMetaElement>('meta[property="csp-nonce"]')?.nonce
    const emotion = [...document.querySelectorAll<HTMLStyleElement>('style[data-emotion]')]
    return { nonce, count: emotion.length, withNonce: emotion.filter((style) => style.nonce === nonce).length }
  })
  expect(styles.nonce).toBe('__CSP_NONCE__')
  expect(styles.count).toBeGreaterThan(0)
  expect(styles.withNonce).toBe(styles.count)
  expect(violations()).toEqual([])
})
