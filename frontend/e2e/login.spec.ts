import { expect, type Page, test } from '@playwright/test'

const username = process.env.E2E_USERNAME ?? 'e2e-user'
const password = process.env.E2E_PASSWORD ?? 'e2e correct horse battery'

/** Collects CSP and Trusted Types violations: console messages and securitypolicyviolation events. */
async function watchCsp(page: Page) {
  const console: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'error' && /Content Security Policy|Trusted ?Type/i.test(msg.text())) console.push(msg.text())
  })
  await page.addInitScript(() => {
    const seen: string[] = []
    Reflect.set(window, 'cspViolations', seen)
    document.addEventListener('securitypolicyviolation', (e) => seen.push(`${e.effectiveDirective} ${e.blockedURI}`))
  })
  return async () => {
    const events = await page.evaluate((): string[] => {
      const seen: unknown = Reflect.get(window, 'cspViolations')
      return Array.isArray(seen) ? seen.map(String) : []
    })
    return [...console, ...events]
  }
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
  expect(await violations()).toEqual([])
})

test('wrong password shows an error', async ({ page }) => {
  await page.goto('/login')
  await signIn(page, 'wrong password')
  await expect(page.getByText('Invalid username or password.')).toBeVisible()
})

test('sends the security headers and the nonce placeholder', async ({ page }) => {
  const response = await page.goto('/login')
  const headers = response?.headers() ?? {}
  expect(headers['content-security-policy']).toContain("style-src 'self' 'nonce-__CSP_NONCE__'")
  expect(headers['content-security-policy']).toContain("require-trusted-types-for 'script'; trusted-types dompurify")
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
