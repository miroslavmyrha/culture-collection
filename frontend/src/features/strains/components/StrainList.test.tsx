import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeLab, makeMe, makeStrainRow, makeTaxon, page, problem } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderApp, renderWithProviders } from '@/test/render'
import { strainListOptions } from '../api/queries'
import type { StrainListParams } from '../schemas'
import { StrainList } from './StrainList'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const LIST = '/api/v1/labs/{lab_public_id}/strains/'
const PARAMS: StrainListParams = { limit: 25, offset: 0 }
// Invented taxa: the tests pair them with restrictions and risk groups, which no real
// organism should be shown with unless the facts hold.
const testella = makeTaxon({ public_id: '00000000-0000-4000-8000-0000000000b1', name: 'Testella', rank: 'genus' })

function renderList(params: StrainListParams = PARAMS) {
  const onOffsetChange = vi.fn<(offset: number) => void>()
  const onClearFilters = vi.fn<() => void>()
  return { onOffsetChange, onClearFilters, view: renderWithProviders(<StrainList labId={LAB_ID} params={params} onOffsetChange={onOffsetChange} onClearFilters={onClearFilters} />) }
}

// Each case renders the list with its filters, and the taxon filter waits for its debounced search:
// real work, so a busy machine runs past the 5 s default (#60).
describe('StrainList', { timeout: 20_000 }, () => {
  it('shows each strain with its number linked, the taxon, the risk group and the restrictions', async () => {
    const strain = makeStrainRow({
      accession_number: 'MYC 7',
      name_as_received: 'T. exempli T1',
      risk_group: 2,
      restrictions: [{ kind: 'dual_use', reference: '1C351.c' }],
    })
    mockApi('get', LIST, page([strain, makeStrainRow({ accession_number: 'MYC 8' })]))
    await renderList().view
    expect(screen.getByText('Loading the strains…')).toBeInTheDocument()
    const table = await screen.findByRole('table', { name: 'Strains' })
    const first = within(table).getAllByRole('row')[1]
    if (!first) throw new Error('no row')
    expect(within(first).getAllByRole('cell').map((cell) => cell.textContent)).toEqual([
      'MYC 7',
      'T. exempli T1',
      strain.taxon.name,
      '2',
      'Dual-use item',
      'Active',
    ])
    expect(within(first).getByRole('link', { name: 'MYC 7' })).toHaveAttribute('href', `/labs/${LAB_ID}/strains/${strain.public_id}`)
  })

  it('says the lab has no strains, and with filters offers to clear them', async () => {
    mockApi('get', LIST, page([]))
    await renderList().view
    expect(await screen.findByText('The lab has no strains yet.')).toBeInTheDocument()
  })

  it('moves the focus on when Clear filters goes with the empty result', async () => {
    signedInApp()
    mockApi('get', LIST, page([]))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/strains`, search: { status: 'restricted' } })
    await screen.findByText(/No strain matches these filters/, undefined, { timeout: 4000 })
    const inList = screen.getAllByRole('button', { name: 'Clear filters' }).find((b) => b.closest('form') === null)
    if (!inList) throw new Error('no Clear filters next to the empty result')
    mockApi('get', LIST, page([makeStrainRow({ accession_number: 'MYC 1' })]))
    await userEvent.setup().click(inList)
    await waitFor(() => expect(router.state.location.search).toEqual({}))
    await screen.findByRole('link', { name: 'MYC 1' })
    await waitFor(() => expect(document.activeElement).not.toBe(document.body))
    expect(screen.getByRole('heading', { level: 1, name: 'Strains of Mycology' })).toHaveFocus()
  })

  it('offers to clear the filters when none matches', async () => {
    mockApi('get', LIST, page([]))
    const { onClearFilters, view } = renderList({ ...PARAMS, risk_group: 3 })
    await view
    expect(await screen.findByText(/No strain matches these filters/)).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(onClearFilters).toHaveBeenCalledOnce()
  })

  it('shows a failed load with a retry that works', async () => {
    allowConsole(/API error 500/)
    mockApiError('get', LIST, 500, problem(500))
    await renderList().view
    expect(await screen.findByText(/Could not load the strains/)).toBeInTheDocument()
    mockApi('get', LIST, page([makeStrainRow({ accession_number: 'MYC 1' })]))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('link', { name: 'MYC 1' })).toBeInTheDocument()
  })

  it('asks for the lab and every filter of the URL, and keeps them in the query key', async () => {
    const calls = mockApi('get', LIST, page([]))
    const params: StrainListParams = { ...PARAMS, taxon: testella.public_id, risk_group: 2, status: 'active', restriction: 'gmo', search: 'MYC' }
    const { view } = renderList(params)
    const { client } = await view
    await screen.findByText(/No strain matches/)
    expect(calls[0]?.url.pathname).toBe(`/api/v1/labs/${LAB_ID}/strains/`)
    expect(Object.fromEntries(calls[0]?.url.searchParams ?? [])).toEqual({
      limit: '25',
      offset: '0',
      taxon: testella.public_id,
      risk_group: '2',
      status: 'active',
      restriction: 'gmo',
      search: 'MYC',
    })
    expect(client.getQueryData(strainListOptions(LAB_ID, params).queryKey)).toBeDefined()
  })
})

const form = () => screen.getByRole('form', { name: 'Filter strains' })

function signedInApp(role: 'viewer' | 'curator' = 'viewer') {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}

// Through the real routes: the filters live in the URL, and the pager keeps the focus.
describe('the strains page', { timeout: 20_000 }, () => {
  const signedIn = signedInApp

  it('keeps a chosen filter when Search is pressed right after choosing it', async () => {
    signedIn()
    const calls = mockApi('get', LIST, page([makeStrainRow()]))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/strains` })
    await screen.findByRole('form', { name: 'Filter strains' }, { timeout: 5000 })
    fireEvent.change(within(form()).getByRole('combobox', { name: 'Risk group' }), { target: { value: '2' } })
    fireEvent.change(within(form()).getByRole('searchbox', { name: 'Number or name' }), { target: { value: 'MYC 4' } })
    // No wait between the two: the navigation of the risk group has not reached the form yet.
    fireEvent.click(within(form()).getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(router.state.location.search).toEqual({ risk_group: 2, search: 'MYC 4' }), { timeout: 5000 })
    await waitFor(() => expect(calls.at(-1)?.url.searchParams.get('risk_group')).toBe('2'), { timeout: 5000 })
    expect(calls.at(-1)?.url.searchParams.get('search')).toBe('MYC 4')
  })

  it('puts each filter into the URL and asks the API with it', async () => {
    signedIn()
    const calls = mockApi('get', LIST, page([makeStrainRow()]))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/strains` })
    const user = userEvent.setup()
    await screen.findByRole('form', { name: 'Filter strains' }, { timeout: 5000 })
    const risk = within(form()).getByRole('combobox', { name: 'Risk group' })
    await user.selectOptions(risk, '2')
    await waitFor(() => expect(router.state.location.search).toEqual({ risk_group: 2 }))
    // The same control keeps the focus after the navigation the choice made.
    await waitFor(() => expect(router.state.status).toBe('idle'))
    expect(within(form()).getByRole('combobox', { name: 'Risk group' })).toBe(risk)
    expect(risk).toHaveFocus()
    await user.selectOptions(within(form()).getByRole('combobox', { name: 'Restriction' }), 'cz_rat')
    await user.type(within(form()).getByRole('searchbox', { name: 'Number or name' }), ' MYC 4 {Enter}')
    await waitFor(() => expect(router.state.location.search).toEqual({ risk_group: 2, restriction: 'cz_rat', search: 'MYC 4' }))
    await waitFor(() => expect(calls.at(-1)?.url.searchParams.get('search')).toBe('MYC 4'))
    expect(calls.at(-1)?.url.searchParams.get('restriction')).toBe('cz_rat')
    await user.click(within(form()).getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(router.state.location.search).toEqual({}))
    const text = within(form()).getByRole('searchbox', { name: 'Number or name' })
    expect(text).toHaveValue('')
    expect(text).toHaveFocus() // the button went with the filters
  })

  it('picks a taxon filter by keyboard in the combobox', async () => {
    signedIn()
    mockApi('get', LIST, page([makeStrainRow()]))
    const search = mockApi('get', '/api/v1/taxa/', page([testella]))
    mockApi('get', '/api/v1/taxa/{public_id}/', testella)
    const { router } = renderApp({ path: `/labs/${LAB_ID}/strains` })
    const user = userEvent.setup()
    const taxon = await screen.findByRole('combobox', { name: 'Taxon' }, { timeout: 5000 })
    await user.click(taxon)
    await user.keyboard('Tes')
    await screen.findByRole('option', { name: /Testella/ }, { timeout: 4000 })
    expect(search.at(-1)?.url.searchParams.get('search')).toBe('Tes')
    await user.keyboard('{ArrowDown}{Enter}')
    await waitFor(() => expect(router.state.location.search).toEqual({ taxon: testella.public_id }))
    // From the URL again: the field shows the taxon's name and keeps the focus.
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Taxon' })).toHaveValue('Testella'))
    expect(screen.getByRole('combobox', { name: 'Taxon' })).toBe(taxon)
    expect(taxon).toHaveFocus()
  })

  it('says when the taxa could not be searched, and when the taxon of the filter could not be loaded', async () => {
    allowConsole(/API error 500/)
    signedIn()
    mockApi('get', LIST, page([makeStrainRow()]))
    mockApiError('get', '/api/v1/taxa/', 500)
    mockApiError('get', '/api/v1/taxa/{public_id}/', 500)
    renderApp({ path: `/labs/${LAB_ID}/strains`, search: { taxon: testella.public_id } })
    const taxon = await screen.findByRole('combobox', { name: 'Taxon' }, { timeout: 5000 })
    expect(await screen.findByText(/Could not load the taxon this list is filtered by/, undefined, { timeout: 4000 })).toBeInTheDocument()
    await userEvent.setup().type(taxon, 'Tes')
    expect(await screen.findByText('Could not search the taxa. Change the text to try again.', undefined, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.queryByText('No taxon has this name')).not.toBeInTheDocument()
  })

  it('falls back to no filter for a junk value in the URL', async () => {
    signedIn()
    const calls = mockApi('get', LIST, page([makeStrainRow()]))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/strains`, search: { risk_group: 9, status: 'lost', taxon: 'x', limit: 'many' } })
    await screen.findByRole('table', { name: 'Strains' }, { timeout: 5000 })
    expect(router.state.location.search).toEqual({})
    expect(calls[0]?.url.searchParams.toString()).toBe('limit=25&offset=0')
  })

  it('keeps the focus on Next while the next page loads and on the last page', async () => {
    signedIn()
    const calls = mockApi('get', LIST, page([makeStrainRow()], { count: 30 }))
    const { router } = renderApp({ path: `/labs/${LAB_ID}/strains` })
    const user = userEvent.setup()
    const next = await screen.findByRole('button', { name: 'Next' }, { timeout: 5000 })
    await user.click(next)
    await waitFor(() => expect(router.state.location.search).toEqual({ offset: 25 }))
    await waitFor(() => expect(calls).toHaveLength(2))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Next' })).toHaveAttribute('aria-disabled', 'true'))
    expect(screen.getByRole('button', { name: 'Next' })).toHaveFocus()
  })

  it('offers no adding of a strain here: strains come from accepted deposits', async () => {
    signedIn('curator')
    mockApi('get', LIST, page([]))
    renderApp({ path: `/labs/${LAB_ID}/strains` })
    expect(await screen.findByText('The lab has no strains yet.', undefined, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Add a strain' })).not.toBeInTheDocument()
  })
})
