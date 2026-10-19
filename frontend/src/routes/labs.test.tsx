import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { pageSearch } from '@/lib/paging'
import { makeLab, makeMe, makeMember, page } from '@/test/factories'
import { mockApi } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const signedIn = () => mockApi('get', '/api/v1/auth/me/', makeMe())

describe('/labs route', () => {
  it('loads the list once, before the page renders', async () => {
    signedIn()
    const calls = mockApi('get', '/api/v1/labs/', page([makeLab({ name: 'Mycology' })]))
    renderApp({ path: '/labs' })
    expect(await screen.findByRole('heading', { name: 'Labs' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Mycology' })).toBeInTheDocument() // no loading state: the loader filled the cache
    expect(screen.getAllByRole('main')).toHaveLength(1) // the page is a section inside the layout's main
    expect(calls).toHaveLength(1)
    expect(calls[0]?.url.searchParams.get('offset')).toBe('0')
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
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Next' }, { timeout: 5000 }))
    await waitFor(() => expect(router.state.location.search).toEqual({ offset: 25 }))
    await waitFor(() => expect(calls.map((c) => c.url.searchParams.get('offset'))).toEqual(['0', '25']))
  })

  it('sends anonymous users to the login page without fetching the list', async () => {
    const calls = mockApi('get', '/api/v1/labs/', page([]))
    const { router } = renderApp({ path: '/labs' })
    expect(await screen.findByRole('heading', { name: 'Sign in' }, { timeout: 5000 })).toBeInTheDocument()
    expect(router.state.location.search).toEqual({ redirect: '/labs' })
    expect(calls).toHaveLength(0)
  })

  // With search params on purpose: a nav link that compares them is not current on /labs?offset=25.
  it.each([
    ['/labs', { offset: 25 }],
    [`/labs/${LAB_ID}`, { offset: 25 }],
  ])('marks Labs as the current page on %s with search %j', async (path, search) => {
    signedIn()
    mockApi('get', '/api/v1/labs/', page([makeLab()], { count: 30 }))
    mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID }))
    mockApi('get', '/api/v1/labs/{lab_public_id}/members/', page([makeMember()], { count: 30 }))
    mockApi('get', '/api/v1/labs/{lab_public_id}/location-grants/', [])
    renderApp({ path, search })
    const nav = await screen.findByRole('navigation', { name: 'Main' }, { timeout: 5000 })
    await waitFor(() => expect(within(nav).getByRole('link', { name: 'Labs' })).toHaveAttribute('aria-current', 'page'))
    expect(within(nav).getByRole('link', { name: 'Home' })).not.toHaveAttribute('aria-current')
  })
})

describe('/labs/$labId route', () => {
  it('loads the lab and its members once, before the page renders', async () => {
    signedIn()
    const lab = mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: 'curator' }))
    const members = mockApi('get', '/api/v1/labs/{lab_public_id}/members/', page([makeMember({ username: 'alice' })]))
    mockApi('get', '/api/v1/labs/{lab_public_id}/location-grants/', [])
    renderApp({ path: `/labs/${LAB_ID}` })
    expect(await screen.findByRole('heading', { name: 'Mycology' }, { timeout: 5000 })).toBeInTheDocument()
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
    await userEvent.setup().click(await screen.findByRole('link', { name: 'Mycology' }, { timeout: 5000 }))
    expect(await screen.findByRole('heading', { name: 'Mycology' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe(`/labs/${LAB_ID}`)
  })
})
