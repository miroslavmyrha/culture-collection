import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { pageSearch } from '@/lib/paging'
import { makeLab, makeMe, makeMember, page } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderApp } from '@/test/render'
import { reported } from '@/test/reports'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const signedIn = () => mockApi('get', '/api/v1/auth/me/', makeMe())
/** The page's own requests: the lab picker in the top bar asks for up to 200 labs on every page. */
const pageCalls = <T extends { url: URL }>(calls: T[]) => calls.filter((call) => call.url.searchParams.get('limit') !== '200')

describe('/labs route', () => {
  it('loads the list once, before the page renders', async () => {
    signedIn()
    const calls = mockApi('get', '/api/v1/labs/', page([makeLab({ name: 'Mycology' })]))
    renderApp({ path: '/labs' })
    expect(await screen.findByRole('heading', { name: 'Labs' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Mycology' })).toBeInTheDocument() // no loading state: the loader filled the cache
    expect(screen.getAllByRole('main')).toHaveLength(1) // the page is a section inside the layout's main
    expect(pageCalls(calls)).toHaveLength(1)
    expect(pageCalls(calls)[0]?.url.searchParams.get('offset')).toBe('0')
  })

  it('falls back to the defaults for bad search values', () => {
    expect(pageSearch.parse({ limit: 'all', offset: -5 })).toEqual({ limit: 25, offset: 0 })
    expect(pageSearch.parse({ limit: 1000 })).toEqual({ limit: 25, offset: 0 })
    expect(pageSearch.parse({})).toEqual({ limit: 25, offset: 0 })
    expect(pageSearch.parse({ limit: 10, offset: 20 })).toEqual({ limit: 10, offset: 20 })
  })

  it('keeps the page in the URL', async () => {
    signedIn()
    const calls = mockApi('get', '/api/v1/labs/', page([makeLab()], { count: 60 }))
    const { router } = renderApp({ path: '/labs', search: { limit: 'oops' } })
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Next' }))
    await waitFor(() => expect(router.state.location.search).toEqual({ offset: 25 }))
    await waitFor(() => expect(pageCalls(calls).map((c) => c.url.searchParams.get('offset'))).toEqual(['0', '25']))
  })

  it('sends anonymous users to the login page without fetching the list', async () => {
    const calls = mockApi('get', '/api/v1/labs/', page([]))
    const { router } = renderApp({ path: '/labs' })
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(router.state.location.search).toEqual({ redirect: '/labs' })
    expect(calls).toHaveLength(0)
  })
})

describe('/labs/$labId route', () => {
  it('loads the lab and its members once, before the page renders', async () => {
    signedIn()
    const lab = mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: 'curator' }))
    const members = mockApi('get', '/api/v1/labs/{lab_public_id}/members/', page([makeMember({ username: 'alice' })]))
    mockApi('get', '/api/v1/labs/{lab_public_id}/location-grants/', [])
    renderApp({ path: `/labs/${LAB_ID}` })
    expect(await screen.findByRole('heading', { name: 'Mycology' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'alice' })).toBeInTheDocument()
    expect([lab.length, members.length]).toEqual([1, 1])
    expect(members[0]?.url.pathname).toBe(`/api/v1/labs/${LAB_ID}/members/`)
  })

  it('opens a lab from the list', async () => {
    signedIn()
    mockApi('get', '/api/v1/labs/', page([makeLab({ public_id: LAB_ID, name: 'Mycology' })]))
    mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology' }))
    mockApi('get', '/api/v1/labs/{lab_public_id}/members/', page([makeMember()]))
    mockApi('get', '/api/v1/labs/{lab_public_id}/location-grants/', [])
    const { router } = renderApp({ path: '/labs' })
    await userEvent.setup().click(await screen.findByRole('link', { name: 'Mycology' }))
    expect(await screen.findByRole('heading', { name: 'Mycology' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe(`/labs/${LAB_ID}`)
  })
})

// #43: the loader fetches a failing list (with its retries) and reports it once; the page then
// shows the failure with its retry, and its mount neither fetches nor reports it again.
describe('a failing page load', () => {
  it('is fetched and reported once, and names the reference of the server failure', async () => {
    signedIn()
    const calls = mockApiError('get', '/api/v1/labs/', 500, { detail: 'boom' }, { headers: { 'Retry-After': '0', 'X-Request-ID': 'req-43' } })
    renderApp({ path: '/labs' })
    expect(await screen.findByText(/Could not load/)).toHaveTextContent('Reference: req-43.')
    await new Promise((resolve) => setTimeout(resolve, 200))
    expect(pageCalls(calls)).toHaveLength(1) // the loader's; tests send no retries
    // The lab picker of the top bar asks the same failing endpoint (limit=200): one report per
    // failing request, and none for a second fetch of the page that no longer happens.
    expect(reported).toHaveLength(calls.length)
  })
})
