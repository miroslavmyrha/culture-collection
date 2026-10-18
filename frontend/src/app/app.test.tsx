import type { AnyRoute } from '@tanstack/react-router'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { authKeys } from '@/features/auth/api/keys'
import { api, unwrap } from '@/lib/api'
import { allowConsole } from '@/test/console'
import { makeMe, problem } from '@/test/factories'
import { holdApi, mockApi, mockApiError } from '@/test/mockApi'
import { renderApp } from '@/test/render'
import { reported } from '@/test/reports'
import { server } from '@/test/server'
import { authenticatedRoute } from '@/routes/authenticated'
import { loginSearchSchema } from '@/routes/login'
import { makeQueryClient } from './query-client'
import { createAppRouter } from './router'

async function signIn(username = 'lab-tech') {
  const user = userEvent.setup()
  await user.type(await screen.findByRole('textbox', { name: 'Username' }), username)
  await user.type(screen.getByLabelText('Password'), 'correct horse battery')
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
  return user
}

/**
 * Records every h1 that was ever in the document, not only the final state: a page that
 * mounts and then redirects in an effect is gone by the time an end-state assertion runs.
 */
function recordHeadings() {
  const seen = new Set<string>()
  const observer = new MutationObserver(() => {
    for (const h of document.querySelectorAll('h1')) seen.add(h.textContent ?? '')
  })
  observer.observe(document.body, { childList: true, subtree: true, characterData: true })
  return { seen, stop: () => observer.disconnect() }
}

function isBelowAuthenticated(route: AnyRoute) {
  for (let parent = route.parentRoute; parent; parent = parent.parentRoute) if (parent.id === authenticatedRoute.id) return true
  return false
}

afterEach(() => {
  vi.unstubAllEnvs()
})

// Invariant: every leaf route under the authenticated layout, including routes added later.
describe('the authenticated layout (invariant)', () => {
  const paths = Object.values<AnyRoute>(createAppRouter(makeQueryClient()).routesById)
    .filter((route) => isBelowAuthenticated(route) && !route.children)
    .map((route) => route.fullPath.replace(/\$\w+/g, 'x'))

  it('has routes to check', () => {
    expect(paths.length).toBeGreaterThan(0)
  })

  it.each(paths)('sends anonymous users from %s to /login without ever mounting the page', async (path) => {
    const headings = recordHeadings()
    const { router } = renderApp({ path })
    // The first render test of the file loads the lazy LoginPage chunk cold. With the whole
    // suite running in parallel that import can take longer than findBy's default 1 s.
    expect(await screen.findByRole('heading', { name: 'Sign in' }, { timeout: 5000 })).toBeInTheDocument()
    headings.stop()
    expect(router.state.location.pathname).toBe('/login')
    expect(router.state.location.search).toEqual({ redirect: path })
    expect([...headings.seen]).toEqual(['Sign in'])
  })
})

describe('routing and the session guard', () => {
  it('sends anonymous users to /login with the page they wanted', async () => {
    const { router } = renderApp({ path: '/', search: { tab: 'b' } })
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
    expect(router.state.location.search).toEqual({ redirect: '/?tab=b' })
  })

  it('accepts the 403 that older backends send for anonymous users', async () => {
    mockApiError('get', '/api/v1/auth/me/', 403, { detail: 'Authentication credentials were not provided.' })
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('signs in, sends the CSRF token and returns to the validated redirect', async () => {
    const me = makeMe({ username: 'lab-tech' })
    const calls = mockApi('post', '/api/v1/auth/login/', me, { status: 200 })
    const { router } = renderApp({ path: '/login', search: { redirect: '/?tab=b' } })
    await signIn()
    expect(await screen.findByText('Signed in as lab-tech')).toBeInTheDocument()
    expect(router.state.location.href).toBe('/?tab=b')
    expect(calls).toHaveLength(1)
    expect(calls[0]?.body).toEqual({ username: 'lab-tech', password: 'correct horse battery' })
    expect(calls[0]?.headers.get('X-CSRFToken')).toBe('test-token')
  })

  it('ignores a hostile redirect', async () => {
    mockApi('post', '/api/v1/auth/login/', makeMe(), { status: 200 })
    const { router } = renderApp({ path: '/login', search: { redirect: '//evil.com/x' } })
    await signIn()
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument()
    expect(router.state.location.href).toBe('/')
  })

  it('keeps the redirect when the login answers 401 (the 401 handler stays out of /login)', async () => {
    const calls = mockApiError('post', '/api/v1/auth/login/', 401, problem(401))
    const { router } = renderApp({ path: '/login', search: { redirect: '/?tab=b' } })
    await signIn()
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password.')
    expect(calls).toHaveLength(1)
    expect(router.state.location.pathname).toBe('/login')
    expect(router.state.location.search).toEqual({ redirect: '/?tab=b' })
  })

  it('validates the login search params with fallbacks', () => {
    expect(loginSearchSchema.parse({ redirect: 42 })).toEqual({ redirect: undefined })
    expect(loginSearchSchema.parse({})).toEqual({})
    expect(loginSearchSchema.parse({ redirect: '/a' })).toEqual({ redirect: '/a' })
  })

  it.each([
    [{}, '/'],
    [{ redirect: '/?tab=b' }, '/?tab=b'],
    [{ redirect: '//evil.com/x' }, '/'],
  ])('sends signed-in users away from /login with search %j to %s', async (search, href) => {
    mockApi('get', '/api/v1/auth/me/', makeMe())
    const { router } = renderApp({ path: '/login', search })
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument()
    expect(router.state.location.href).toBe(href)
  })

  // /..//evil.com resolves on our origin but normalises to //evil.com. The router refuses that
  // href in a beforeLoad redirect with an error, so a helper that only checks its input shows
  // the route error screen here instead of the start page.
  it('sends a signed-in user on /login?redirect=/..//evil.com to the start page, never to the error screen', async () => {
    mockApi('get', '/api/v1/auth/me/', makeMe())
    const headings = recordHeadings()
    const { router } = renderApp({ path: '/login', search: { redirect: '/..//evil.com' } })
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument()
    headings.stop()
    expect(router.state.location.href).toBe('/')
    expect([...headings.seen]).not.toContain('Something went wrong')
  })

  it('returns to the start page after signing in with a dot-segment redirect', async () => {
    mockApi('post', '/api/v1/auth/login/', makeMe(), { status: 200 })
    const { router } = renderApp({ path: '/login', search: { redirect: '/a/..//evil.com' } })
    await signIn()
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeInTheDocument()
    expect(router.state.location.href).toBe('/')
  })

  it('shows not found for an unknown URL', async () => {
    renderApp({ path: '/no-such-page' })
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})

const anonymous = () => undefined // the default handler answers /auth/me/ with 401
const signedIn = () => void mockApi('get', '/api/v1/auth/me/', makeMe())

describe('base layout', () => {
  // The layout owns the one <main>: a page that adds its own would nest landmarks.
  it.each([
    ['/login', 'Sign in', anonymous],
    ['/', 'Home', signedIn],
    ['/no-such-page', 'Page not found', anonymous],
  ])('renders %s inside the top bar and exactly one main landmark', async (path, heading, session) => {
    session()
    renderApp({ path })
    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument()
    expect(screen.getByRole('banner')).toHaveTextContent('Culture collection')
    expect(screen.getAllByRole('main')).toHaveLength(1)
    expect(screen.getByRole('main')).toContainElement(screen.getByRole('heading', { name: heading }))
  })
})

describe('app shell', () => {
  // With search params on purpose: a link that compares them would not be current on /?tab=b.
  it('shows the main navigation, the user and sign out with a session', async () => {
    mockApi('get', '/api/v1/auth/me/', makeMe({ username: 'lab-tech' }))
    renderApp({ path: '/', search: { tab: 'b' } })
    const nav = await screen.findByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: 'Home' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('banner')).toHaveTextContent('Signed in as lab-tech')
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
  })

  it('shows neither navigation nor sign out without a session', async () => {
    renderApp({ path: '/login' })
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument() // no "signed out" without signing out
  })

  it('starts with a skip link to the main content', async () => {
    renderApp({ path: '/login' })
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    await userEvent.setup().tab()
    const skip = screen.getByRole('link', { name: 'Skip to content' })
    expect(skip).toHaveFocus()
    expect(skip).toHaveAttribute('href', `#${screen.getByRole('main').id}`)
  })

  it('requests /auth/me/ once when it fails: the shell reads the cache, it does not fetch', async () => {
    allowConsole(/API error 500|Error in route match/)
    const calls = mockApiError('get', '/api/v1/auth/me/', 500)
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Something went wrong' })).toBeInTheDocument()
    expect(calls).toHaveLength(1)
  })
})

describe('session expiry (401)', () => {
  it('clears the cache and redirects to /login with the current page', async () => {
    mockApi('get', '/api/v1/auth/me/', makeMe({ username: 'lab-tech' }))
    const { router, client } = renderApp({ path: '/', search: { tab: 'b' } })
    expect(await screen.findByText('Signed in as lab-tech')).toBeInTheDocument()
    // The session ends: every API call now answers 401.
    mockApiError('get', '/api/v1/auth/me/', 401, problem(401))
    mockApiError('get', '/api/v1/auth/csrf/', 401, problem(401))
    const csrf = (n: number) => client.fetchQuery({ queryKey: ['csrf', n], queryFn: () => unwrap(api.GET('/api/v1/auth/csrf/')) })
    await Promise.allSettled([csrf(1), csrf(2), csrf(3)])
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(router.state.location.search).toEqual({ redirect: '/?tab=b' })
    expect(client.getQueryCache().findAll({ queryKey: ['csrf'] })).toHaveLength(0)
    expect(client.getQueryData(authKeys.me())).toBeNull()
    // The always-mounted top bar follows the session, not the user it rendered first.
    expect(screen.queryByText(/Signed in as/)).not.toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
  })

  // The router updates its location synchronously on navigate, so without a blocker the
  // pathname check alone stops the later 401s. The redirecting flag matters while a
  // navigation blocker (an unsaved-changes dialog) holds the redirect.
  it('asks to navigate once for repeated 401s while a blocker holds the redirect', async () => {
    mockApi('get', '/api/v1/auth/me/', makeMe({ username: 'lab-tech' }))
    const { router, client } = renderApp()
    expect(await screen.findByText('Signed in as lab-tech')).toBeInTheDocument()
    const blockerFn = vi.fn<() => Promise<boolean>>(() => new Promise<boolean>(() => {})) // the dialog stays open
    router.history.block({ blockerFn })
    mockApiError('get', '/api/v1/auth/csrf/', 401, problem(401))
    // One after another, not in parallel: the first 401 clears the cache, which cancels queries
    // still in flight without calling onError, so parallel 401s reach the handler by timing.
    for (const n of [1, 2, 3]) {
      await client.fetchQuery({ queryKey: ['csrf', n], queryFn: () => unwrap(api.GET('/api/v1/auth/csrf/')) }).catch(() => undefined)
    }
    expect(blockerFn).toHaveBeenCalledOnce()
  })
})

describe('sign out', () => {
  it('clears the cache and shows the login page', async () => {
    mockApi('get', '/api/v1/auth/me/', makeMe({ username: 'lab-tech' }))
    const { client } = renderApp()
    const user = userEvent.setup()
    const button = await screen.findByRole('button', { name: 'Sign out' })
    mockApiError('get', '/api/v1/auth/me/', 401, problem(401))
    mockApi('post', '/api/v1/auth/logout/', undefined)
    await user.click(button)
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(client.getQueryData(authKeys.me())).toBeNull()
    expect(screen.getByRole('status')).toHaveTextContent('You have been signed out.')
    expect(screen.queryByText(/Signed in as/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument()
  })

  it('counts a 401 from logout as signed out: the session was already gone', async () => {
    mockApi('get', '/api/v1/auth/me/', makeMe({ username: 'lab-tech' }))
    const { client, router } = renderApp()
    client.setQueryData(['private', 'records'], ['secret'])
    const button = await screen.findByRole('button', { name: 'Sign out' })
    mockApiError('get', '/api/v1/auth/me/', 401, problem(401))
    mockApiError('post', '/api/v1/auth/logout/', 401, problem(401))
    await userEvent.setup().click(button)
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(router.state.location.search).toEqual({ signedOut: true })
    expect(screen.getByRole('status')).toHaveTextContent('You have been signed out.')
    expect(client.getQueryData(['private', 'records'])).toBeUndefined()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  // The server session may still be valid: showing a sign-in form would tell someone who is
  // still signed in that they are not, and the next person at a shared PC reloads into it.
  it.each([
    ['a server error', [{ source: 'mutation' }], () => mockApiError('post', '/api/v1/auth/logout/', 500)],
    ['a CSRF failure', [], () => mockApiError('post', '/api/v1/auth/logout/', 403, problem(403, { code: 'csrf_failed' }))],
    [
      'a network error',
      [{ source: 'mutation' }],
      () => {
        const calls: unknown[] = []
        server.use(
          http.post('*/api/v1/auth/logout/', () => {
            calls.push(null)
            return HttpResponse.error()
          }),
        )
        return calls
      },
    ],
  ])('keeps the session, the data and the page after %s, and says so', async (_, reports, failLogout) => {
    mockApi('get', '/api/v1/auth/me/', makeMe({ username: 'lab-tech' }))
    const { client, router } = renderApp({ path: '/', search: { tab: 'b' } })
    client.setQueryData(['private', 'records'], ['secret'])
    const user = userEvent.setup()
    const button = await screen.findByRole('button', { name: 'Sign out' })
    const calls = failLogout()
    await user.click(button)
    expect(await screen.findByRole('alert')).toHaveTextContent('Sign-out failed. You are still signed in. Try again.')
    expect(calls).toHaveLength(1)
    expect(reported.map((r) => r.context)).toEqual(reports) // a 4xx is an answer, not a bug
    expect(router.state.location.href).toBe('/?tab=b')
    expect(screen.getByRole('heading', { name: 'Home' })).toBeInTheDocument()
    expect(screen.getByText('Signed in as lab-tech')).toBeInTheDocument()
    expect(client.getQueryData(['private', 'records'])).toEqual(['secret'])
    expect(client.getQueryData(authKeys.me())).toMatchObject({ username: 'lab-tech' })
    // The button keeps the focus and works again.
    expect(button).toHaveFocus()
    expect(button).not.toBeDisabled()
    expect(button).toHaveAttribute('aria-disabled', 'false')
    await user.click(button)
    await waitFor(() => expect(calls).toHaveLength(2))
  })

  it('signs out on a retry after a failure, and the failure notice does not follow to the login page', async () => {
    mockApi('get', '/api/v1/auth/me/', makeMe({ username: 'lab-tech' }))
    renderApp()
    const user = userEvent.setup()
    const button = await screen.findByRole('button', { name: 'Sign out' })
    server.use(http.post('*/api/v1/auth/logout/', () => HttpResponse.json(problem(503), { status: 503 }), { once: true }))
    await user.click(button)
    expect(await screen.findByRole('alert')).toHaveTextContent('Sign-out failed.')
    mockApi('post', '/api/v1/auth/logout/', undefined)
    mockApiError('get', '/api/v1/auth/me/', 401, problem(401))
    await user.click(button)
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('You have been signed out.')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('ignores a second click while the sign-out request runs', async () => {
    mockApi('get', '/api/v1/auth/me/', makeMe({ username: 'lab-tech' }))
    const { client } = renderApp()
    const user = userEvent.setup()
    const button = await screen.findByRole('button', { name: 'Sign out' })
    const logout = holdApi('post', '/api/v1/auth/logout/')
    mockApiError('get', '/api/v1/auth/me/', 401, problem(401))
    await user.click(button)
    await waitFor(() => expect(button).toHaveAttribute('aria-disabled', 'true'))
    expect(button).toHaveFocus()
    await user.click(button)
    expect(client.isMutating()).toBe(1) // a second mutate would count at once, before its request
    logout.release(204)
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(logout.calls).toHaveLength(1)
  })
})

describe('route errors', () => {
  it('shows a generic message with retry, and the raw message only in development', async () => {
    allowConsole(/API error 500|Error in route match/)
    vi.stubEnv('DEV', false)
    mockApiError('get', '/api/v1/auth/me/', 500, { detail: 'stack trace with secrets' })
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Something went wrong' })).toBeInTheDocument()
    expect(screen.getByText('The server failed. Try again in a moment.')).toBeInTheDocument()
    expect(screen.queryByText(/API error 500|secrets/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload the page' })).toBeInTheDocument()
    // Reported once, by the query cache (the route does not report API errors again).
    expect(reported.map((r) => r.context.source)).toEqual(['query'])

    mockApi('get', '/api/v1/auth/me/', makeMe({ username: 'back' }))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Signed in as back')).toBeInTheDocument()
  })

  it('shows the raw message in development', async () => {
    allowConsole(/API error 500|Error in route match/)
    mockApiError('get', '/api/v1/auth/me/', 500)
    renderApp()
    expect(await screen.findByText('API error 500')).toBeInTheDocument()
  })
})
