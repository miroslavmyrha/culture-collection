import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { preferences } from '@/lib/storage'
import { makeLab, makeMe, makeStrainRow, page } from '@/test/factories'
import { mockApi } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const OTHER_ID = '00000000-0000-4000-8000-00000000000b'
const STRAINS = '/api/v1/labs/{lab_public_id}/strains/'
const signedIn = () => void mockApi('get', '/api/v1/auth/me/', makeMe({ username: 'lab-tech' }))
const labs = () => mockApi('get', '/api/v1/labs/', page([makeLab({ public_id: LAB_ID, name: 'Mycology' }), makeLab({ public_id: OTHER_ID, name: 'Bacteriology' })]))
const lab = (role: 'viewer' | 'curator' = 'viewer') => mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
const scheme = () => document.documentElement.getAttribute('data-color-scheme')

/** jsdom has no matchMedia: the stub answers the prefers-color-scheme query. */
function systemPrefers(dark: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query.includes('dark') ? dark : false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }))
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.documentElement.removeAttribute('data-color-scheme')
})

async function openAccountMenu(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Account (lab-tech)' }, { timeout: 5000 }))
  return screen.findByRole('menu', { name: 'Account (lab-tech)' })
}

describe('the colour scheme switch', () => {
  it('follows the system by default: dark when the system prefers it, light otherwise', async () => {
    signedIn()
    systemPrefers(true)
    renderApp({ path: '/' })
    await openAccountMenu(userEvent.setup())
    await waitFor(() => expect(scheme()).toBe('dark'))
    expect(screen.getByRole('menuitemradio', { name: 'System' })).toHaveAttribute('aria-checked', 'true')
  })

  it('is light when the system prefers light', async () => {
    signedIn()
    systemPrefers(false)
    renderApp({ path: '/' })
    await openAccountMenu(userEvent.setup())
    await waitFor(() => expect(scheme()).toBe('light'))
  })

  it('remembers the choice per browser and applies it over the system setting', async () => {
    signedIn()
    systemPrefers(false)
    const user = userEvent.setup()
    renderApp({ path: '/' })
    const menu = await openAccountMenu(user)
    await user.click(within(menu).getByRole('menuitemradio', { name: 'Dark' }))
    await waitFor(() => expect(scheme()).toBe('dark'))
    expect(preferences.get('scheme')).toBe('dark')
  })

  it('starts from a remembered choice', async () => {
    signedIn()
    systemPrefers(false)
    preferences.set('scheme', 'dark')
    renderApp({ path: '/' })
    const menu = await openAccountMenu(userEvent.setup())
    await waitFor(() => expect(scheme()).toBe('dark'))
    expect(within(menu).getByRole('menuitemradio', { name: 'Dark' })).toHaveAttribute('aria-checked', 'true')
    expect(within(menu).getByRole('menuitemradio', { name: 'System' })).toHaveAttribute('aria-checked', 'false')
  })

  it('ignores a stored value that is not a mode', async () => {
    signedIn()
    systemPrefers(false)
    preferences.set('scheme', 'sepia')
    renderApp({ path: '/' })
    const menu = await openAccountMenu(userEvent.setup())
    expect(within(menu).getByRole('menuitemradio', { name: 'System' })).toHaveAttribute('aria-checked', 'true')
  })

  it('works without storage: the switch applies for the session and nothing throws', async () => {
    signedIn()
    systemPrefers(false)
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage blocked')
    })
    const user = userEvent.setup()
    renderApp({ path: '/' })
    const menu = await openAccountMenu(user)
    await user.click(within(menu).getByRole('menuitemradio', { name: 'Dark' }))
    await waitFor(() => expect(scheme()).toBe('dark'))
    vi.restoreAllMocks()
  })
})

describe('the lab picker', () => {
  it('shows the current lab and lists the user labs with the current one checked', async () => {
    signedIn()
    labs()
    lab()
    mockApi('get', STRAINS, page([makeStrainRow()]))
    renderApp({ path: `/labs/${LAB_ID}/strains` })
    const user = userEvent.setup()
    const picker = await screen.findByRole('button', { name: 'Lab Mycology' }, { timeout: 5000 })
    expect(picker).toHaveAttribute('aria-haspopup', 'menu')
    await user.click(picker)
    const menu = await screen.findByRole('menu', { name: 'Lab Mycology' })
    expect(within(menu).getByRole('menuitemradio', { name: 'Mycology' })).toHaveAttribute('aria-checked', 'true')
    expect(within(menu).getByRole('menuitemradio', { name: 'Bacteriology' })).toHaveAttribute('aria-checked', 'false')
    expect(within(menu).getByRole('menuitem', { name: 'All labs' })).toBeInTheDocument()
  })

  it('opens the same section of another lab, by keyboard', async () => {
    signedIn()
    labs()
    lab()
    mockApi('get', STRAINS, page([makeStrainRow()]))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/strains` })
    const user = userEvent.setup()
    const picker = await screen.findByRole('button', { name: 'Lab Mycology' }, { timeout: 5000 })
    picker.focus()
    await user.keyboard('{ArrowDown}')
    await waitFor(() => expect(screen.getByRole('menuitemradio', { name: 'Mycology' })).toHaveFocus()) // the checked one
    await user.keyboard('{ArrowDown}{Enter}')
    await waitFor(() => expect(router.state.location.pathname).toBe(`/labs/${OTHER_ID}/strains`))
  })

  it('opens the lab page from a page that is not one of the shared sections', async () => {
    signedIn()
    labs()
    lab()
    mockApi('get', '/api/v1/labs/{lab_public_id}/members/', page([]))
    mockApi('get', '/api/v1/labs/{lab_public_id}/location-grants/', [])
    const { router } = renderApp({ path: `/labs/${LAB_ID}` })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Lab Mycology' }, { timeout: 5000 }))
    await user.click(await screen.findByRole('menuitem', { name: 'All labs' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/labs'))
  })

  it('says so when the user is in no lab', async () => {
    signedIn()
    mockApi('get', '/api/v1/labs/', page([]))
    renderApp({ path: '/' })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /^(Lab|Select a lab)/ }, { timeout: 5000 }))
    expect(await screen.findByRole('menuitem', { name: 'You are in no lab' })).toHaveAttribute('aria-disabled', 'true')
  })
})

describe('the lab tabs', () => {
  it('shows the three sections to a viewer, with the current one marked', async () => {
    signedIn()
    labs()
    lab('viewer')
    mockApi('get', STRAINS, page([makeStrainRow()]))
    renderApp({ path: `/labs/${LAB_ID}/strains` })
    const nav = await screen.findByRole('navigation', { name: 'Lab sections' }, { timeout: 5000 })
    const links = within(nav).getAllByRole('link')
    expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
      ['Strains', `/labs/${LAB_ID}/strains`],
      ['Storage', `/labs/${LAB_ID}/storage`],
      ['Requests', `/labs/${LAB_ID}/requests`],
    ])
    expect(links.map((link) => link.getAttribute('aria-current'))).toEqual(['page', null, null])
  })

  it('adds deposits, depositors and MTA templates for a curator', async () => {
    signedIn()
    labs()
    lab('curator')
    mockApi('get', STRAINS, page([]))
    renderApp({ path: `/labs/${LAB_ID}/strains` })
    const nav = await screen.findByRole('navigation', { name: 'Lab sections' }, { timeout: 5000 })
    await waitFor(() => expect(within(nav).getAllByRole('link').map((link) => link.textContent)).toEqual(['Strains', 'Storage', 'Requests', 'Deposits', 'Depositors', 'MTA templates']))
  })

  it('is not there outside a lab', async () => {
    signedIn()
    labs()
    renderApp({ path: '/labs' })
    expect(await screen.findByRole('heading', { name: 'Labs' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Lab sections' })).not.toBeInTheDocument()
  })

  it('moves between the tabs by keyboard, one Tab stop each, and marks the new page', async () => {
    signedIn()
    labs()
    lab('viewer')
    mockApi('get', STRAINS, page([]))
    mockApi('get', '/api/v1/labs/{lab_public_id}/storage-units/', [])
    const { router } = renderApp({ path: `/labs/${LAB_ID}/strains` })
    const user = userEvent.setup()
    const nav = await screen.findByRole('navigation', { name: 'Lab sections' }, { timeout: 5000 })
    within(nav).getByRole('link', { name: 'Strains' }).focus()
    await user.tab()
    expect(within(nav).getByRole('link', { name: 'Storage' })).toHaveFocus()
    await user.keyboard('{Enter}')
    await waitFor(() => expect(router.state.location.pathname).toBe(`/labs/${LAB_ID}/storage`))
    await waitFor(() => expect(within(nav).getByRole('link', { name: 'Storage' })).toHaveAttribute('aria-current', 'page'))
    expect(within(nav).getByRole('link', { name: 'Strains' })).not.toHaveAttribute('aria-current')
  })

  // jsdom has no layout, so the 320 px fit is measured in the e2e; here: the row scrolls inside
  // itself (not the page), keeps its tabs on one line, and brings the active tab into view.
  it('scrolls inside its own row and brings the active tab into view', async () => {
    const scrollIntoView = vi.fn<(options?: ScrollIntoViewOptions) => void>()
    Element.prototype.scrollIntoView = scrollIntoView
    signedIn()
    labs()
    lab('curator')
    mockApi('get', STRAINS, page([]))
    renderApp({ path: `/labs/${LAB_ID}/strains` })
    const nav = await screen.findByRole('navigation', { name: 'Lab sections' }, { timeout: 5000 })
    const row = within(nav).getAllByRole('link')[0]?.parentElement
    expect(row).toBeTruthy()
    if (!row) return
    expect(getComputedStyle(row).overflowX).toBe('auto')
    for (const link of within(nav).getAllByRole('link')) {
      expect(getComputedStyle(link).whiteSpace).toBe('nowrap')
      expect(getComputedStyle(link).flexShrink).toBe('0')
    }
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled())
    // @ts-expect-error jsdom has none: remove the stub again
    delete Element.prototype.scrollIntoView
  })
})
