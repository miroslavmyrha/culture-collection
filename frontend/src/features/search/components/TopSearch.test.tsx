import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeSearchGroup, makeSearchHit, SEARCH_LAB } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { TopSearch } from './TopSearch'

const SEARCH = '/api/v1/me/search/'
const STRAIN = '00000000-0000-4000-8000-0000000000f1'
const VIAL = '00000000-0000-4000-8000-0000000000e1'

const strains = () =>
  makeSearchGroup({
    kind: 'strain',
    total: 12,
    hits: [makeSearchHit({ public_id: STRAIN, identifier: 'BAC 2', exact: true, detail: 'Received as hay isolate' }), makeSearchHit({ identifier: 'BAC 20', title: 'Micrococcus luteus' })],
  })
const vials = () =>
  makeSearchGroup({
    kind: 'vial',
    hits: [
      makeSearchHit({
        public_id: VIAL,
        identifier: 'BAC 29 / 1 / 3',
        status: 'available',
        exact: true,
        strain: STRAIN,
        location: { box: '00000000-0000-4000-8000-0000000000b1', box_name: 'Seed stock 1', path: ['LN2 tank 1', 'Canister A', 'Seed stock 1'], row: 1, col: 3, label: 'A3' },
      }),
    ],
  })
const masked = () =>
  makeSearchGroup({
    kind: 'vial',
    hits: [makeSearchHit({ identifier: 'REG 1 / 1 / 1', lab_code: 'REG', title: 'Mockia vulgaris', status: 'available', exact: true, strain: STRAIN, detail: 'Barcode TUBE-R', location_masked: true })],
  })

const box = () => screen.getByRole('combobox', { name: 'Search' })
const listbox = () => screen.findByRole('listbox', { name: 'Search results' }, { timeout: 5000 })
const render = (compact = false) => renderWithProviders(<TopSearch compact={compact} />)

describe('the top bar search', () => {
  it('asks once typing pauses, with the text folded, and nothing for one character', async () => {
    const calls = mockApi('get', SEARCH, { groups: [strains()] })
    const user = userEvent.setup()
    await render()
    await user.type(box(), 'B')
    await new Promise((resolve) => setTimeout(resolve, 400))
    // Enter does not ask for one character either.
    await user.keyboard('{Enter}')
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(calls).toHaveLength(0)
    expect(box()).toHaveAttribute('aria-expanded', 'false')
    await user.type(box(), 'AC   2')
    await listbox()
    expect(calls).toHaveLength(1)
    expect(calls[0]?.url.searchParams.get('q')).toBe('BAC 2')
  })

  it('groups the results by kind with the number, lab and status, and names every option in full', async () => {
    mockApi('get', SEARCH, { groups: [strains(), vials()] })
    const user = userEvent.setup()
    await render()
    await user.type(box(), 'BAC 2')
    const list = await listbox()
    const strainGroup = within(list).getByRole('group', { name: 'Strains, 12 strains' })
    expect(within(strainGroup).getAllByRole('option').map((o) => o.getAttribute('aria-label'))).toEqual([
      'BAC 2, BAC, Active. Bacillus subtilis, Received as hay isolate',
      'BAC 20, BAC, Active. Micrococcus luteus',
      'All 12 strains in BAC',
    ])
    const vialGroup = within(list).getByRole('group', { name: 'Vials, 1 vial' })
    expect(within(vialGroup).getByRole('option')).toHaveAccessibleName('BAC 29 / 1 / 3, BAC, Available. Bacillus subtilis, LN2 tank 1 / Canister A / Seed stock 1, A3')
    // Vials have no list page: no "All" entry.
    expect(within(vialGroup).getAllByRole('option')).toHaveLength(1)
    expect(await screen.findByRole('status')).toHaveTextContent('13 results: 12 strains, 1 vial.')
  })

  it('says a regulated vial’s place is hidden and names its strain’s lab, never a box', async () => {
    mockApi('get', SEARCH, { groups: [masked()] })
    const user = userEvent.setup()
    await render()
    await user.type(box(), 'TUBE-R')
    const option = within(await listbox()).getByRole('option')
    expect(option).toHaveAccessibleName('REG 1 / 1 / 1, REG, Available. Mockia vulgaris, Place hidden: regulated strain, Barcode TUBE-R')
    expect(option).toHaveTextContent('Place hidden: regulated strain')
  })

  it('moves the active option with the arrows, keeps the focus in the field and opens it with Enter', async () => {
    mockApi('get', SEARCH, { groups: [strains(), vials()] })
    const user = userEvent.setup()
    const { router } = await render()
    await user.type(box(), 'BAC 2')
    const options = within(await listbox()).getAllByRole('option')
    expect(box()).not.toHaveAttribute('aria-activedescendant')
    await user.keyboard('{ArrowDown}')
    expect(box()).toHaveAttribute('aria-activedescendant', options[0]?.id)
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}')
    // It stops at the last option.
    expect(box()).toHaveAttribute('aria-activedescendant', options[3]?.id)
    await user.keyboard('{ArrowUp}{ArrowUp}')
    expect(box()).toHaveAttribute('aria-activedescendant', options[1]?.id)
    expect(options[0]).toHaveAttribute('aria-selected', 'false')
    expect(box()).toHaveFocus()
    await user.keyboard('{ArrowUp}{ArrowUp}')
    expect(box()).not.toHaveAttribute('aria-activedescendant')
    await user.keyboard('{ArrowDown}{Enter}')
    await waitFor(() => expect(router.state.location.pathname).toBe(`/labs/${SEARCH_LAB}/strains/${STRAIN}`))
  })

  it('opens the list of all matches of a lab, filtered by the text', async () => {
    mockApi('get', SEARCH, { groups: [strains()] })
    const user = userEvent.setup()
    const { router } = await render()
    await user.type(box(), 'BAC 2')
    await user.click(within(await listbox()).getByRole('option', { name: 'All 12 strains in BAC' }))
    await waitFor(() => expect(router.state.location.pathname).toBe(`/labs/${SEARCH_LAB}/strains`))
    expect(router.state.location.search).toEqual({ search: 'BAC 2' })
  })

  it('opens a vial on its strain’s Material tab, narrowed to it', async () => {
    mockApi('get', SEARCH, { groups: [vials()] })
    const user = userEvent.setup()
    const { router } = await render()
    await user.type(box(), 'BAC 29 / 1 / 3')
    await user.click(within(await listbox()).getByRole('option'))
    await waitFor(() => expect(router.state.location.pathname).toBe(`/labs/${SEARCH_LAB}/strains/${STRAIN}/material`))
    expect(router.state.location.search).toEqual({ vial: VIAL })
  })

  it('opens what a scanned code names on Enter, without waiting for the list', async () => {
    const calls = mockApi('get', SEARCH, { groups: [vials()] })
    const user = userEvent.setup()
    const { router } = await render()
    // A scanner types the code and Enter at once: the debounce has not run yet.
    await user.type(box(), 'TUBE-1{Enter}')
    await waitFor(() => expect(router.state.location.pathname).toBe(`/labs/${SEARCH_LAB}/strains/${STRAIN}/material`))
    expect(router.state.location.search).toEqual({ vial: VIAL })
    expect(calls[0]?.url.searchParams.get('q')).toBe('TUBE-1')
  })

  it('keeps the list open on Enter when the text names more than one hit exactly', async () => {
    mockApi('get', SEARCH, { groups: [strains(), vials()] })
    const user = userEvent.setup()
    const { router } = await render()
    await user.type(box(), 'BAC 2{Enter}')
    await listbox()
    expect(router.state.location.pathname).toBe('/')
  })

  it('closes the list on Escape, then clears the field', async () => {
    mockApi('get', SEARCH, { groups: [strains()] })
    const user = userEvent.setup()
    await render()
    await user.type(box(), 'BAC 2')
    await listbox()
    await user.keyboard('{ArrowDown}{Escape}')
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(box()).toHaveAttribute('aria-expanded', 'false')
    expect(box()).not.toHaveAttribute('aria-activedescendant')
    expect(box()).toHaveValue('BAC 2')
    await user.keyboard('{Escape}')
    expect(box()).toHaveValue('')
    expect(box()).toHaveFocus()
  })

  it('says when nothing matches', async () => {
    mockApi('get', SEARCH, { groups: [] })
    const user = userEvent.setup()
    await render()
    await user.type(box(), 'zz')
    expect(await screen.findByText(/^No results for “zz”\./, {}, { timeout: 5000 })).toBeVisible()
    expect(screen.getByRole('status')).toHaveTextContent('No results.')
    // A message alone is no list: the field says so.
    expect(box()).toHaveAttribute('aria-expanded', 'false')
  })

  it('says why a search failed, and Enter asks again', async () => {
    allowConsole(/API error 500/)
    mockApiError('get', SEARCH, 500)
    const user = userEvent.setup()
    await render()
    await user.type(box(), 'BAC 2')
    expect(await screen.findByText(/^Search failed\. .* Press Enter to try again\.$/, {}, { timeout: 5000 })).toBeVisible()
    expect(screen.getByRole('status')).toHaveTextContent(/^Search failed\./)
    // No exact hit this time, so Enter shows the list instead of opening one.
    const calls = mockApi('get', SEARCH, { groups: [makeSearchGroup({ hits: [makeSearchHit({ identifier: 'BAC 20' })] })] })
    await user.keyboard('{Enter}')
    await listbox()
    expect(calls).toHaveLength(1)
  })

  it('takes the focus on /, but not while typing in another field or with a modifier', async () => {
    const user = userEvent.setup()
    await renderWithProviders(
      <>
        <label>
          Other <input />
        </label>
        <TopSearch compact={false} />
      </>,
    )
    await user.click(screen.getByRole('textbox', { name: 'Other' }))
    await user.keyboard('/')
    expect(screen.getByRole('textbox', { name: 'Other' })).toHaveValue('/')
    expect(box()).not.toHaveFocus()
    await user.click(document.body)
    await user.keyboard('{Control>}/{/Control}')
    expect(box()).not.toHaveFocus()
    await user.keyboard('/')
    expect(box()).toHaveFocus()
    // The slash is the shortcut, not text.
    expect(box()).toHaveValue('')
    expect(box()).toHaveAttribute('aria-keyshortcuts', '/')
  })

  it('is a Search button below sm that opens a full-width field and closes back to the button', async () => {
    const user = userEvent.setup()
    await render(true)
    expect(screen.queryByRole('combobox')).toBeNull()
    const button = screen.getByRole('button', { name: 'Search' })
    expect(button).toHaveAttribute('aria-expanded', 'false')
    await user.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    await waitFor(() => expect(box()).toHaveFocus())
    expect(document.getElementById(button.getAttribute('aria-controls') ?? '')).toContainElement(box())
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(button).toHaveFocus()
    // The shortcut opens it too.
    await user.keyboard('/')
    await waitFor(() => expect(box()).toHaveFocus())
  })
})
