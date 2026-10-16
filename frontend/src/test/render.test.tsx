import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole, assertNoConsoleOutput, watchConsole } from './console'
import { renderHookWithProviders, renderWithProviders } from './render'

function SearchProbe() {
  const search = useSearch({ strict: false })
  const navigate = useNavigate()
  return (
    <>
      <output>{JSON.stringify(search)}</output>
      {/* Links and navigate are typed by the app's registered routes. */}
      <button type="button" onClick={() => void navigate({ to: '/login', search: { redirect: '/x' } })}>
        Go
      </button>
    </>
  )
}

function Cached({ label }: { label: string }) {
  const q = useQuery({ queryKey: ['k'], queryFn: () => 'from cache' })
  return <p>{`${label}: ${q.data ?? ''}`}</p>
}

describe('renderWithProviders', () => {
  it('renders at the given path and search, and exposes the router', async () => {
    const user = userEvent.setup()
    const { router } = await renderWithProviders(<SearchProbe />, { path: '/samples', search: { page: 2, q: 'x' } })
    expect(screen.getByRole('status')).toHaveTextContent('{"page":2,"q":"x"}')
    expect(router.state.location.pathname).toBe('/samples')
    await user.click(screen.getByRole('button', { name: 'Go' }))
    await waitFor(() => expect(router.state.location.href).toBe('/login?redirect=%2Fx'))
    expect(screen.getByRole('status')).toHaveTextContent('{"redirect":"/x"}')
  })

  it('keeps the providers on rerender', async () => {
    const { rerender, client } = await renderWithProviders(<Cached label="a" />)
    client.setQueryData(['k'], 'from cache')
    rerender(<Cached label="b" />)
    expect(await screen.findByText('b: from cache')).toBeInTheDocument()
  })
})

describe('renderHookWithProviders', () => {
  it('runs a hook with the query client and router', async () => {
    const { result } = await renderHookWithProviders(() => useSearch({ strict: false }), { path: '/x', search: { tab: 'a' } })
    await waitFor(() => expect(result.current).toEqual({ tab: 'a' }))
  })
})

describe('test environment', () => {
  it('runs in UTC', () => {
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe('UTC')
    expect(new Date(0).getHours()).toBe(0)
  })

  it('starts every test with empty storage', () => {
    expect(localStorage.length).toBe(0)
    localStorage.setItem('leak', '1')
  })

  it('cleared the storage of the previous test', () => {
    expect(localStorage.getItem('leak')).toBeNull()
  })

  it('lets a test allow an expected console message', () => {
    allowConsole(/expected warning/)
    /* oxlint-disable no-console -- the point of the test */
    console.warn('an expected warning')
    expect(console.warn).toHaveBeenCalledOnce()
    /* oxlint-enable no-console */
  })

  // Without this test a guard that never throws keeps the whole suite green.
  it('fails on an unexpected console.error', () => {
    // oxlint-disable-next-line no-console -- the point of the test
    console.error('boom')
    expect(() => assertNoConsoleOutput()).toThrow('console.error: boom')
    watchConsole() // start clean, so this test's own afterEach passes
  })
})
