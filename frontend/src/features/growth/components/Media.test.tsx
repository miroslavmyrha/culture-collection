import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { makeMedium, page, problem, validationProblem } from '@/test/factories'
import { holdApi, mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { sharedKeys } from '@/lib/shared-keys'
import { MediaList } from './MediaList'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const LIST = '/api/v1/labs/{lab_public_id}/media/'
const ONE = '/api/v1/labs/{lab_public_id}/media/{public_id}/'
const RETIRE = '/api/v1/labs/{lab_public_id}/media/{public_id}/retire/'
const lb = makeMedium({ name: 'LB', composition_reference: 'DSMZ medium 381' })
const old = makeMedium({ name: 'Old agar', retired_at: '2026-10-01T10:00:00Z' })

const render = (canManage = true) => renderWithProviders(<MediaList labId={LAB_ID} canManage={canManage} />)

describe('MediaList', { timeout: 15_000 }, () => {
  it('lists the media with their reference and status, and gives the retired no actions', async () => {
    mockApi('get', LIST, page([lb, old]))
    await render()
    const table = await screen.findByRole('table', { name: 'Media' })
    const first = within(table).getByRole('row', { name: /^LB/ })
    const second = within(table).getByRole('row', { name: /^Old agar/ })
    expect(first).toHaveTextContent('LBDSMZ medium 381Active')
    expect(within(first).getByRole('button', { name: 'Edit medium LB' })).toBeInTheDocument()
    expect(second).toHaveTextContent('Old agarNoneRetired 2026-10-01')
    expect(within(second).queryByRole('button')).not.toBeInTheDocument()
  })

  it('shows no actions and no add button to someone who may not manage', async () => {
    mockApi('get', LIST, page([lb]))
    await render(false)
    await screen.findByRole('table', { name: 'Media' })
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('says when there is none, and how many are hidden', async () => {
    mockApi('get', LIST, page([]))
    const view = await render()
    expect(await screen.findByText('The lab has no medium yet.')).toBeInTheDocument()
    view.unmount()
    mockApi('get', LIST, page([lb], { count: 250 }))
    await render()
    expect(await screen.findByText('Showing the first 1 of 250 media.')).toBeInTheDocument()
  })

  it('adds a medium, refreshes the lists that show media, and puts the focus back', async () => {
    const reads = mockApi('get', LIST, page([lb]))
    const calls = mockApi('post', LIST, makeMedium({ name: 'R2A' }))
    const { client } = await render()
    client.setQueryData(sharedKeys.strainLists(LAB_ID), [])
    const user = userEvent.setup()
    const add = await screen.findByRole('button', { name: 'Add a medium' })
    await user.click(add)
    const dialog = await screen.findByRole('dialog', { name: 'Add a medium' })
    await waitFor(() => expect(within(dialog).getByRole('textbox', { name: 'Name' })).toHaveFocus())
    await user.type(within(dialog).getByRole('textbox', { name: 'Name' }), '  R2A ')
    await user.type(within(dialog).getByRole('textbox', { name: 'Composition reference' }), 'DSMZ medium 830')
    await user.click(within(dialog).getByRole('button', { name: 'Add medium' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ name: 'R2A', composition_reference: 'DSMZ medium 830' })
    expect(calls[0]?.headers.get('X-CSRFToken')).toBe('test-token')
    await waitFor(() => expect(reads).toHaveLength(2))
    expect(client.getQueryState(sharedKeys.strainLists(LAB_ID))?.isInvalidated).toBe(true)
    await waitFor(() => expect(add).toHaveFocus())
  })

  it('refuses an empty name without a request, on the field', async () => {
    mockApi('get', LIST, page([lb]))
    const calls = recordRequests('post', LIST)
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Add a medium' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a medium' })
    await user.click(within(dialog).getByRole('button', { name: 'Add medium' }))
    await waitFor(() => expect(within(dialog).getByRole('textbox', { name: 'Name' })).toHaveAccessibleDescription(/Enter the name of the medium$/))
    expect(calls).toHaveLength(0)
  })

  it('puts a taken name on the name field and keeps the dialog open', async () => {
    mockApi('get', LIST, page([lb]))
    mockApiError('post', LIST, 400, validationProblem([{ attr: 'name', code: 'unique', detail: 'The lab has a medium of this name.' }]))
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Add a medium' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add a medium' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'LB')
    await user.click(within(dialog).getByRole('button', { name: 'Add medium' }))
    await waitFor(() => expect(within(dialog).getByRole('textbox', { name: 'Name' })).toHaveAccessibleDescription(/The lab has a medium of this name\.$/))
    expect(dialog).toBeInTheDocument()
  })

  it('edits a medium from its own values', async () => {
    mockApi('get', LIST, page([lb]))
    const calls = mockApi('put', ONE, lb)
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Edit medium LB' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit LB' })
    expect(within(dialog).getByRole('textbox', { name: 'Composition reference' })).toHaveValue('DSMZ medium 381')
    await user.clear(within(dialog).getByRole('textbox', { name: 'Name' }))
    await user.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'LB broth')
    await user.click(within(dialog).getByRole('button', { name: 'Save medium' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ name: 'LB broth', composition_reference: 'DSMZ medium 381' })
    expect(calls[0]?.url.pathname).toBe(`/api/v1/labs/${LAB_ID}/media/${lb.public_id}/`)
  })

  it('retires a medium only with a reason, and refreshes the strains and passages that show it', async () => {
    mockApi('get', LIST, page([lb]))
    const calls = mockApi('post', RETIRE, { ...lb, retired_at: '2026-10-02T10:00:00Z' })
    const { client } = await render()
    client.setQueryData(sharedKeys.strainLists(LAB_ID), [])
    client.setQueryData(sharedKeys.strainMaterial(LAB_ID, 's1'), [])
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Retire medium LB' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Retire LB?' })
    await user.click(within(dialog).getByRole('button', { name: 'Retire medium' }))
    await waitFor(() => expect(within(dialog).getByRole('textbox', { name: 'Reason' })).toHaveAccessibleDescription(/Say why$/))
    expect(calls).toHaveLength(0)
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'Replaced by R2A')
    await user.click(within(dialog).getByRole('button', { name: 'Retire medium' }))
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(calls[0]?.body).toEqual({ reason: 'Replaced by R2A' })
    expect(client.getQueryState(sharedKeys.strainLists(LAB_ID))?.isInvalidated).toBe(true)
    expect(client.getQueryState(sharedKeys.strainMaterial(LAB_ID, 's1'))?.isInvalidated).toBe(true)
  })

  it('names a 409 for a medium retired meanwhile in its own words, and keeps the button focusable while it sends', async () => {
    mockApi('get', LIST, page([lb]))
    const held = holdApi('post', RETIRE)
    await render()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Retire medium LB' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Retire LB?' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Reason' }), 'x')
    const confirm = within(dialog).getByRole('button', { name: 'Retire medium' })
    await user.click(confirm)
    await waitFor(() => expect(confirm).toHaveAttribute('aria-disabled', 'true'))
    await user.click(confirm)
    expect(held.calls).toHaveLength(1)
    held.release(409, problem(409, { code: 'medium_retired', detail: 'server words' }))
    expect(await within(dialog).findByText('This medium is retired. Close this and reload the list.')).toBeInTheDocument()
    expect(screen.queryByText('server words')).not.toBeInTheDocument()
  })
})
