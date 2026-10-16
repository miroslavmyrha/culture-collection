import type { AnyRoute } from '@tanstack/react-router'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { authKeys } from '@/features/auth/api/keys'
import { api, unwrap } from '@/lib/api'
import { allowConsole } from '@/test/console'
import { makeMe, problem } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderApp } from '@/test/render'
import { reported } from '@/test/reports'
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

  it('shows not found for an unknown URL', async () => {
    renderApp({ path: '/no-such-page' })
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
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
  })

  it('still clears the cache when the logout request fails, and says so', async () => {
    mockApi('get', '/api/v1/auth/me/', makeMe({ username: 'lab-tech' }))
    const { client } = renderApp()
    client.setQueryData(['private', 'records'], ['secret'])
    const user = userEvent.setup()
    const button = await screen.findByRole('button', { name: 'Sign out' })
    mockApiError('post', '/api/v1/auth/logout/', 500)
    mockApiError('get', '/api/v1/auth/me/', 401, problem(401))
    await user.click(button)
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(client.getQueryData(['private', 'records'])).toBeUndefined()
    expect(screen.getByRole('alert')).toHaveTextContent('The server failed. Try again in a moment.')
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
