import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeDeposit, makeLab, makeMe, makeMember, makeMtaTemplate, makeStrain, makeStrainRow, page, problem } from '@/test/factories'
import { holdApi, mockApi, mockApiError } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const STRAINS = '/api/v1/labs/{lab_public_id}/strains/'
const STRAIN = '/api/v1/labs/{lab_public_id}/strains/{public_id}/'
const DEPOSITORS = '/api/v1/labs/{lab_public_id}/depositors/'
const MTAS = '/api/v1/labs/{lab_public_id}/mta-templates/'
const MTA = '/api/v1/labs/{lab_public_id}/mta-templates/{public_id}/'
const DEPOSITS = '/api/v1/labs/{lab_public_id}/deposits/'
const DEPOSIT = '/api/v1/labs/{lab_public_id}/deposits/{public_id}/'
const signedIn = (username = 'lab-tech') => void mockApi('get', '/api/v1/auth/me/', makeMe({ username }))
const lab = (overrides = {}) => mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', ...overrides }))
const members = (count = 1) => mockApi('get', '/api/v1/labs/{lab_public_id}/members/', page([makeMember()], { count }))

/** jsdom has no matchMedia, so MUI's useMediaQuery answers false (the wide bar) unless stubbed. */
function narrowScreen() {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query.includes('max-width'),
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
})

describe('page titles (WCAG 2.4.2)', () => {
  // Every state a page can be in, also errors and not found: a tab keeps the previous page's
  // title when a state renders none.
  it.each([
    ['/login', 'Sign in', () => undefined],
    ['/', 'Home', () => signedIn()],
    ['/labs', 'Labs', () => (signedIn(), mockApi('get', '/api/v1/labs/', page([makeLab()])))],
    [`/labs/${LAB_ID}`, 'Mycology', () => (signedIn(), lab(), members())],
    [`/labs/${LAB_ID}`, 'Lab not found', () => (signedIn(), mockApiError('get', '/api/v1/labs/{public_id}/', 404, problem(404)), members())],
    [`/labs/${LAB_ID}`, 'Could not load the lab', () => (signedIn(), mockApiError('get', '/api/v1/labs/{public_id}/', 500), members())],
    [`/labs/${LAB_ID}/strains`, 'Strains of Mycology', () => (signedIn(), lab(), mockApi('get', STRAINS, page([makeStrainRow()])))],
    [`/labs/${LAB_ID}/strains`, 'Lab not found', () => (signedIn(), mockApiError('get', '/api/v1/labs/{public_id}/', 404, problem(404)), mockApi('get', STRAINS, page([])))],
    [`/labs/${LAB_ID}/strains/${STRAIN_ID}`, 'MYC 42', () => (signedIn(), lab(), mockApi('get', STRAIN, makeStrain({ public_id: STRAIN_ID, accession_number: 'MYC 42' })))],
    [`/labs/${LAB_ID}/strains/${STRAIN_ID}`, 'Strain not found', () => (signedIn(), lab(), mockApiError('get', STRAIN, 404, problem(404)))],
    [`/labs/${LAB_ID}/strains/${STRAIN_ID}`, 'Could not load the strain', () => (signedIn(), lab(), mockApiError('get', STRAIN, 500))],
    [`/labs/${LAB_ID}/depositors`, 'Depositors of Mycology', () => (signedIn(), lab({ my_role: 'curator' }), mockApi('get', DEPOSITORS, page([])))],
    [`/labs/${LAB_ID}/mta-templates`, 'MTA templates of Mycology', () => (signedIn(), lab({ my_role: 'curator' }), mockApi('get', MTAS, page([])))],
    [`/labs/${LAB_ID}/mta-templates/new`, 'Publish an MTA version in Mycology', () => (signedIn(), lab({ my_role: 'manager' }))],
    [`/labs/${LAB_ID}/mta-templates/${STRAIN_ID}`, 'STD version 1', () => (signedIn(), lab({ my_role: 'curator' }), mockApi('get', MTA, makeMtaTemplate()))],
    [`/labs/${LAB_ID}/mta-templates/${STRAIN_ID}`, 'MTA not found', () => (signedIn(), lab({ my_role: 'curator' }), mockApiError('get', MTA, 404, problem(404)))],
    [`/labs/${LAB_ID}/mta-templates/${STRAIN_ID}`, 'MTA template', () => (signedIn(), lab({ my_role: 'viewer' }), mockApiError('get', MTA, 404, problem(404)))],
    [`/labs/${LAB_ID}/deposits`, 'Deposits of Mycology', () => (signedIn(), lab({ my_role: 'curator' }), mockApi('get', DEPOSITS, page([])))],
    [`/labs/${LAB_ID}/deposits/new`, 'Receive a deposit in Mycology', () => (signedIn(), lab({ my_role: 'curator' }), mockApi('get', MTAS, page([])))],
    [`/labs/${LAB_ID}/deposits/${STRAIN_ID}`, 'Deposit Testella K3', () => (signedIn(), lab({ my_role: 'curator' }), mockApi('get', DEPOSIT, makeDeposit({ name_as_received: 'Testella K3' })))],
    [`/labs/${LAB_ID}/deposits/${STRAIN_ID}`, 'Deposit not found', () => (signedIn(), lab({ my_role: 'curator' }), mockApiError('get', DEPOSIT, 404, problem(404)))],
    [`/labs/${LAB_ID}/deposits/${STRAIN_ID}`, 'Could not load the deposit', () => (signedIn(), lab({ my_role: 'curator' }), mockApiError('get', DEPOSIT, 500))],
    [`/labs/${LAB_ID}/deposits/${STRAIN_ID}`, 'Deposit', () => (signedIn(), lab({ my_role: 'viewer' }), mockApiError('get', DEPOSIT, 404, problem(404)))],
    ['/no-such-page', 'Page not found', () => undefined],
  ])('%s shows "%s | Culture collection"', async (path, title, setup) => {
    allowConsole(/API error 500/)
    setup()
    renderApp({ path })
    await waitFor(() => expect(document.title).toBe(`${title} | Culture collection`), { timeout: 5000 })
    expect(document.querySelectorAll('title')).toHaveLength(1)
  })

  it('titles the route error screen', async () => {
    allowConsole(/API error 500|Error in route match/)
    mockApiError('get', '/api/v1/auth/me/', 500)
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Something went wrong' })).toBeInTheDocument()
    expect(document.title).toBe('Something went wrong | Culture collection')
    expect(document.querySelectorAll('title')).toHaveLength(1)
  })

  it('titles the loading states', async () => {
    signedIn()
    const held = holdApi('get', '/api/v1/labs/{public_id}/')
    members()
    renderApp({ path: `/labs/${LAB_ID}` })
    // The router's pending screen first (the loader waits for the lab), then the page's own.
    await waitFor(() => expect(document.title).toMatch(/^Loading( the lab)? \| Culture collection$/), { timeout: 5000 })
    expect(document.querySelectorAll('title')).toHaveLength(1)
    held.release(200, makeLab({ public_id: LAB_ID, name: 'Mycology' }))
    await waitFor(() => expect(document.title).toBe('Mycology | Culture collection'), { timeout: 5000 })
    expect(document.querySelectorAll('title')).toHaveLength(1)
  })
})

describe('focus after navigation (WCAG 2.4.3)', () => {
  it('leaves the focus alone on the first load', async () => {
    signedIn()
    mockApi('get', '/api/v1/labs/', page([makeLab()]))
    renderApp({ path: '/labs' })
    expect(await screen.findByRole('heading', { level: 1, name: 'Labs' }, { timeout: 5000 })).toBeInTheDocument()
    // Give a late onRendered the chance to run.
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(document.body).toHaveFocus()
  })

  it('focuses the h1 of the page a link opened', async () => {
    signedIn()
    mockApi('get', '/api/v1/labs/', page([makeLab({ public_id: LAB_ID, name: 'Mycology' })]))
    lab()
    members()
    renderApp({ path: '/labs' })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('link', { name: 'Mycology' }, { timeout: 5000 }))
    const heading = await screen.findByRole('heading', { level: 1, name: 'Mycology' })
    await waitFor(() => expect(heading).toHaveFocus())
    expect(heading).toHaveAttribute('tabindex', '-1') // a target, not a tab stop
  })

  it('focuses the h1 after moving through the main navigation by keyboard', async () => {
    signedIn()
    mockApi('get', '/api/v1/labs/', page([makeLab()]))
    renderApp({ path: '/' })
    const nav = await screen.findByRole('navigation', { name: 'Main' }, { timeout: 5000 })
    within(nav).getByRole('link', { name: 'Labs' }).focus()
    await userEvent.setup().keyboard('{Enter}')
    const heading = await screen.findByRole('heading', { level: 1, name: 'Labs' }, { timeout: 5000 })
    await waitFor(() => expect(heading).toHaveFocus())
  })

  it('keeps the focus on Next when the pager changes only the search', async () => {
    signedIn()
    const calls = mockApi('get', '/api/v1/labs/', page([makeLab()], { count: 60 }))
    const { router } = renderApp({ path: '/labs' })
    const user = userEvent.setup()
    const next = await screen.findByRole('button', { name: 'Next' }, { timeout: 5000 })
    await user.click(next)
    await waitFor(() => expect(router.state.location.search).toEqual({ offset: 25 }))
    await waitFor(() => expect(calls).toHaveLength(2))
    await waitFor(() => expect(router.state.status).toBe('idle'))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(screen.getByRole('button', { name: 'Next' })).toHaveFocus()
  })

  it('does not move the focus when only the hash changes, or when the new URL has one', async () => {
    signedIn()
    mockApi('get', '/api/v1/labs/', page([makeLab()]))
    const { router } = renderApp({ path: '/' })
    expect(await screen.findByRole('heading', { level: 1, name: 'Home' }, { timeout: 5000 })).toBeInTheDocument()
    await router.navigate({ to: '/', hash: 'part' })
    await router.navigate({ to: '/labs', hash: 'part' })
    expect(await screen.findByRole('heading', { level: 1, name: 'Labs' }, { timeout: 5000 })).toBeInTheDocument()
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(document.body).toHaveFocus()
  })

  it('focuses main when the new page has no h1', async () => {
    signedIn()
    mockApiError('get', '/api/v1/labs/{public_id}/', 503)
    members()
    allowConsole(/API error 503/)
    const { router } = renderApp({ path: '/' })
    expect(await screen.findByRole('heading', { level: 1, name: 'Home' }, { timeout: 5000 })).toBeInTheDocument()
    await router.navigate({ to: '/labs/$labId', params: { labId: LAB_ID } })
    expect(await screen.findByText(/Could not load the lab/, {}, { timeout: 5000 })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('main')).toHaveFocus())
  })

  it('focuses the h1 of the page a retry loaded, not the body', async () => {
    signedIn()
    mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology' }))
    members()
    allowConsole(/API error 503/)
    mockApiError('get', '/api/v1/labs/{public_id}/', 503)
    renderApp({ path: `/labs/${LAB_ID}` })
    const retry = await screen.findByRole('button', { name: 'Try again' }, { timeout: 5000 })
    lab()
    await userEvent.setup().click(retry)
    const heading = await screen.findByRole('heading', { level: 1, name: 'Mycology' })
    await waitFor(() => expect(heading).toHaveFocus())
  })
})

describe('focus after a retry on the route error screen', () => {
  it('goes to the h1 of the page that loaded', async () => {
    allowConsole(/API error 500|Error in route match/)
    mockApiError('get', '/api/v1/auth/me/', 500)
    renderApp({ path: '/' })
    const retry = await screen.findByRole('button', { name: 'Try again' }, { timeout: 5000 })
    signedIn()
    await userEvent.setup().click(retry)
    const heading = await screen.findByRole('heading', { level: 1, name: 'Home' }, { timeout: 5000 })
    await waitFor(() => expect(heading).toHaveFocus())
  })
})

describe('the account menu on a narrow screen (WCAG 1.4.10)', () => {
  it('replaces the user text and Sign out with a named menu button', async () => {
    narrowScreen()
    signedIn('lab-tech')
    renderApp({ path: '/' })
    const button = await screen.findByRole('button', { name: 'Account (lab-tech)' }, { timeout: 5000 })
    expect(button).toHaveTextContent('lab-tech') // the visible label is part of the name (WCAG 2.5.3)
    expect(button).toHaveAttribute('aria-haspopup', 'menu')
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Signed in as lab-tech')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument()
  })

  it('works by keyboard: Enter opens on Sign out, arrows stay, Escape returns to the button, ArrowDown opens', async () => {
    narrowScreen()
    signedIn('lab-tech')
    renderApp({ path: '/' })
    const user = userEvent.setup()
    const button = await screen.findByRole('button', { name: 'Account (lab-tech)' }, { timeout: 5000 })
    button.focus()
    await user.keyboard('{Enter}')
    const menu = await screen.findByRole('menu', { name: 'Account (lab-tech)' })
    expect(button).toHaveAttribute('aria-expanded', 'true')
    expect(button).toHaveAttribute('aria-controls', menu.id)
    const item = within(menu).getByRole('menuitem', { name: 'Sign out' })
    await waitFor(() => expect(item).toHaveFocus())
    await user.keyboard('{ArrowDown}')
    expect(item).toHaveFocus() // one item: the arrows keep it
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
    expect(button).toHaveFocus()
    expect(button).toHaveAttribute('aria-expanded', 'false')
    await user.keyboard('{ArrowDown}')
    await waitFor(() => expect(screen.getByRole('menuitem', { name: 'Sign out' })).toHaveFocus())
  })

  it('signs out from the menu', async () => {
    narrowScreen()
    signedIn('lab-tech')
    const { router } = renderApp({ path: '/' })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Account (lab-tech)' }, { timeout: 5000 }))
    mockApi('post', '/api/v1/auth/logout/', undefined)
    await user.click(await screen.findByRole('menuitem', { name: 'Sign out' }))
    const heading = await screen.findByRole('heading', { name: 'Sign in' }, { timeout: 5000 })
    expect(router.state.location.search).toEqual({ signedOut: true })
    await waitFor(() => expect(heading).toHaveFocus()) // the menu button is gone: the new page's h1
  })

  it('shows a failed sign-out under the bar and returns the focus to the menu button when it is closed', async () => {
    narrowScreen()
    allowConsole(/API error 500/)
    signedIn('lab-tech')
    renderApp({ path: '/' })
    const user = userEvent.setup()
    const button = await screen.findByRole('button', { name: 'Account (lab-tech)' }, { timeout: 5000 })
    await user.click(button)
    mockApiError('post', '/api/v1/auth/logout/', 500)
    await user.click(await screen.findByRole('menuitem', { name: 'Sign out' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Sign-out failed. You are still signed in. Try again.')
    expect(alert.compareDocumentPosition(screen.getByRole('main')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await waitFor(() => expect(button).toHaveFocus()) // the menu returned it
    await user.click(within(alert).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(button).toHaveFocus()
  })
})

describe('the wide bar', () => {
  it('returns the focus to Sign out when the failure notice is closed', async () => {
    allowConsole(/API error 500/)
    signedIn('lab-tech')
    renderApp({ path: '/' })
    const user = userEvent.setup()
    const button = await screen.findByRole('button', { name: 'Sign out' }, { timeout: 5000 })
    expect(screen.queryByRole('button', { name: /^Account/ })).not.toBeInTheDocument()
    mockApiError('post', '/api/v1/auth/logout/', 500)
    await user.click(button)
    const alert = await screen.findByRole('alert')
    await user.click(within(alert).getByRole('button', { name: 'Close' }))
    expect(button).toHaveFocus()
  })
})
