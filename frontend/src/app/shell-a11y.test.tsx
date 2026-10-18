import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeMe } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const signedIn = (username = 'lab-tech') => void mockApi('get', '/api/v1/auth/me/', makeMe({ username }))
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
    expect(await screen.findByRole('heading', { name: 'Sign in' }, { timeout: 5000 })).toBeInTheDocument()
    expect(router.state.location.search).toEqual({ signedOut: true })
  })

  it('shows a failed sign-out under the bar', async () => {
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
  })
})
