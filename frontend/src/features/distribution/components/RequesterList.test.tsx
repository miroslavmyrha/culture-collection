import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { makeLab, makeMe, makePermit, makeRequester, page, validationProblem } from '@/test/factories'
import { mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const LIST = '/api/v1/labs/{lab_public_id}/requesters/'
const PERMITS = '/api/v1/labs/{lab_public_id}/recipient-permits/'

function signedIn(role: 'viewer' | 'curator' | 'manager' = 'curator') {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}

const loa = makePermit({ kind: 'plant_health_loa', reference: 'LoA DEV/1', covers: 'Mockia vulgaris', quantity_allowed: 4, sendings_allowed: 2, expires_on: '2026-12-31' })
const institute = makeRequester({ institution: 'Example Institute', permits: [loa] })

describe('the requesters page', { timeout: 30_000 }, () => {
  it('shows each requester with its laboratory, scientist and permits, each file downloadable', async () => {
    signedIn()
    mockApi('get', LIST, page([institute]))
    renderApp({ path: `/labs/${LAB_ID}/requesters` })
    const card = await screen.findByRole('article', { name: 'Example Institute' }, { timeout: 5000 })
    expect(card).toHaveTextContent('Responsible scientist: Petra Ukázková, petra@example.org.')
    expect(card).toHaveTextContent('Microbiology laboratory confirmed on 2026-10-01')
    const permits = within(card).getByRole('table', { name: 'Permits of Example Institute' })
    expect(within(permits).getAllByRole('row')[1]).toHaveTextContent('Letter of Authority for a quarantine pest: LoA DEV/1 (SÚJB). Names: Mockia vulgaris. 4 allowed in 2 sendings')
    expect(within(permits).getByRole('link', { name: 'Download' })).toHaveAttribute('href', `${window.location.origin}/api/v1/labs/${LAB_ID}/documents/${loa.document.public_id}/`)
  })

  it('tells a viewer that requesters are for curators, without loading them', async () => {
    signedIn('viewer')
    const calls = recordRequests('get', LIST)
    renderApp({ path: `/labs/${LAB_ID}/requesters` })
    expect(await screen.findByText('Only curators and managers see requesters: they name people.', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(calls.filter((c) => c.url.pathname.endsWith('/requesters/') && c.url.searchParams.get('limit') === '25')).toHaveLength(calls.length)
  })

  // jsdom's File inside Node's fetch fails with a content-length mismatch (undici), so the
  // request is caught at the client: what it would send is read from its form data. The real
  // upload runs in the browser in e2e (distribution.spec.ts).
  it('adds a permit with its file as multipart form data, the fields of its kind only', async () => {
    signedIn()
    mockApi('get', LIST, page([institute]))
    renderApp({ path: `/labs/${LAB_ID}/requesters` })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Add a permit of Example Institute' }, { timeout: 5000 }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a permit of Example Institute' })
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Kind' }), 'gmo_contained_use')
    await user.type(within(dialog).getByRole('textbox', { name: 'Issued by' }), 'MŽP')
    await user.type(within(dialog).getByRole('textbox', { name: 'Reference' }), 'DEV/GMO/1')
    await user.type(within(dialog).getByRole('textbox', { name: 'Valid from' }), '2026-01-01')
    await user.type(within(dialog).getByRole('textbox', { name: 'Category' }), '2')
    expect(within(dialog).queryByRole('textbox', { name: 'Agents or pests it names' })).not.toBeInTheDocument()
    const file = new File(['%PDF-1.4'], 'authorisation.pdf', { type: 'application/pdf' })
    await user.upload(within(dialog).getByLabelText('File of the document'), file)
    const post = vi.spyOn(api, 'POST').mockResolvedValue({ data: makePermit(), response: new Response('{}', { status: 201 }) })
    await user.click(within(dialog).getByRole('button', { name: 'Add the permit' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    const [path, init]: unknown[] = post.mock.calls[0] ?? []
    expect(path).toBe('/api/v1/labs/{lab_public_id}/recipient-permits/')
    const serializer: unknown = typeof init === 'object' && init !== null ? Reflect.get(init, 'bodySerializer') : undefined
    if (typeof serializer !== 'function') throw new Error('the permit is sent without its form data')
    const sent: unknown = Reflect.apply(serializer, undefined, [])
    if (!(sent instanceof FormData)) throw new Error('not form data')
    expect(Object.fromEntries([...sent.entries()].filter(([k]) => k !== 'file'))).toEqual({
      requester: institute.public_id,
      kind: 'gmo_contained_use',
      issuer: 'MŽP',
      issuer_country: 'CZ',
      reference: 'DEV/GMO/1',
      valid_from: '2026-01-01',
      covers: '',
      endorsement_reference: '',
      gmo_category: '2',
    })
    const sentFile = sent.get('file')
    expect(sentFile instanceof File && sentFile.name).toBe('authorisation.pdf')
  })

  it('adds a requester with its registered office, the address in the business register', async () => {
    signedIn()
    mockApi('get', LIST, page([institute]))
    const calls = mockApi('post', LIST, makeRequester())
    renderApp({ path: `/labs/${LAB_ID}/requesters` })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Add a requester' }, { timeout: 5000 }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a requester' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Institution' }), 'Example Seat Institute')
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Legal form' }), 'legal_person')
    const seat = within(dialog).getByRole('textbox', { name: 'Registered office' })
    expect(seat).toHaveAccessibleDescription('The address of the institution in the business register. Not the delivery address.')
    await user.type(seat, ' Vzorová 12, 602 00 Brno ')
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Country' }), 'CZ')
    await user.type(within(dialog).getByRole('textbox', { name: 'How the laboratory was confirmed' }), 'The department page.')
    await user.type(within(dialog).getByRole('textbox', { name: 'Responsible scientist' }), 'Petra Ukázková')
    await user.type(within(dialog).getByRole('textbox', { name: 'Delivery address of the laboratory' }), 'Testovací 5, Brno')
    await user.click(within(dialog).getByRole('button', { name: 'Add the requester' }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]?.body).toMatchObject({ seat: 'Vzorová 12, 602 00 Brno', postal_address: 'Testovací 5, Brno', institution: 'Example Seat Institute' })
  })

  it('shows the stored registered office when a requester is changed, and sends it back', async () => {
    signedIn()
    const seated = makeRequester({ institution: 'Seated Institute', seat: 'Vzorová 12, 602 00 Brno' })
    mockApi('get', LIST, page([seated]))
    const calls = mockApi('put', `${LIST}{public_id}/`, seated)
    renderApp({ path: `/labs/${LAB_ID}/requesters` })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Change Seated Institute' }, { timeout: 5000 }))
    const dialog = await screen.findByRole('dialog', { name: 'Change Seated Institute' })
    expect(within(dialog).getByRole('textbox', { name: 'Registered office' })).toHaveValue('Vzorová 12, 602 00 Brno')
    await user.click(within(dialog).getByRole('button', { name: 'Save the requester' }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]?.body).toMatchObject({ seat: 'Vzorová 12, 602 00 Brno' })
  })

  it('shows the server error of the registered office on its field', async () => {
    signedIn()
    const seated = makeRequester({ institution: 'Seated Institute' })
    mockApi('get', LIST, page([seated]))
    mockApiError('put', `${LIST}{public_id}/`, 400, validationProblem([{ attr: 'seat', code: 'max_length', detail: 'Ensure this field has no more than 300 characters.' }]))
    renderApp({ path: `/labs/${LAB_ID}/requesters` })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Change Seated Institute' }, { timeout: 5000 }))
    const dialog = await screen.findByRole('dialog', { name: 'Change Seated Institute' })
    await user.click(within(dialog).getByRole('button', { name: 'Save the requester' }))
    const seat = within(dialog).getByRole('textbox', { name: 'Registered office' })
    await waitFor(() => expect(seat).toHaveAccessibleDescription(/no more than 300 characters/))
  })

  it('refuses a permit without its file before sending', async () => {
    signedIn()
    mockApi('get', LIST, page([institute]))
    renderApp({ path: `/labs/${LAB_ID}/requesters` })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Add a permit of Example Institute' }, { timeout: 5000 }))
    const dialog = await screen.findByRole('dialog')
    const calls = recordRequests('post', PERMITS)
    await user.click(within(dialog).getByRole('button', { name: 'Add the permit' }))
    await waitFor(() => expect(within(dialog).getByRole('combobox', { name: 'Kind' })).toHaveFocus())
    expect(within(dialog).getByText(/Choose the file of the document/)).toBeInTheDocument()
    expect(calls).toHaveLength(0)
  })
})
