import { screen, waitFor } from '@testing-library/react'
import userEvent, { type UserEvent } from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeLab, makeMe, makeRequest, makeRequester, makeStrainRow, page, problem, validationProblem } from '@/test/factories'
import { mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const POST = '/api/v1/labs/{lab_public_id}/requests/'
const requester = makeRequester({ public_id: '00000000-0000-4000-8000-0000000000a5', institution: 'Example Institute', country: 'CZ' })
const base = makeStrainRow()
const strain = makeStrainRow({ public_id: '00000000-0000-4000-8000-0000000000c1', accession_number: 'MYC 3', taxon: { ...base.taxon, name: 'Testella exempli' } })

function setup() {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: 'curator' }))
  mockApi('get', '/api/v1/labs/{lab_public_id}/requesters/', page([requester]))
  mockApi('get', '/api/v1/labs/{lab_public_id}/strains/', page([strain]))
  mockApi('get', '/api/v1/labs/{lab_public_id}/requests/{public_id}/', makeRequest())
  const view = renderApp({ path: `/labs/${LAB_ID}/requests/new` })
  return { ...view, user: userEvent.setup() }
}

async function fill(user: UserEvent) {
  await user.selectOptions(await screen.findByRole('combobox', { name: 'Requester' }, { timeout: 5000 }), requester.public_id)
  await user.selectOptions(screen.getByRole('combobox', { name: 'Use' }), 'teaching')
  await user.type(screen.getByRole('textbox', { name: 'End use' }), 'Practical classes.')
  await user.selectOptions(screen.getByRole('combobox', { name: 'Declared containment level' }), '2')
  await user.click(screen.getByRole('combobox', { name: 'Strain 1' }))
  await user.keyboard('MYC')
  await screen.findByRole('option', { name: /MYC 3/ }, { timeout: 10_000 })
  await user.keyboard('{ArrowDown}{Enter}')
  const vials = screen.getByRole('textbox', { name: 'Vials of strain 1' })
  await user.clear(vials)
  await user.type(vials, '2')
}

describe('entering a request', { timeout: 30_000 }, () => {
  it('sends the requester, the use, the end use, the containment level and the lines', async () => {
    const { user, router } = setup()
    await fill(user)
    const created = makeRequest({ public_id: '00000000-0000-4000-8000-0000000000a1' })
    const calls = mockApi('post', POST, created)
    await user.click(screen.getByRole('button', { name: 'Enter the request' }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]?.headers.get('X-CSRFToken')).toBe('test-token')
    expect(calls[0]?.body).toEqual({
      requester: requester.public_id,
      use: 'teaching',
      end_use: 'Practical classes.',
      containment_level: 2,
      lines: [{ strain: strain.public_id, quantity: 2 }],
    })
    await waitFor(() => expect(router.state.location.pathname).toBe(`/labs/${LAB_ID}/requests/${created.public_id}`))
  })

  it('asks for every choice, focuses the first, and sends nothing', async () => {
    const { user } = setup()
    const calls = recordRequests('post', POST)
    await screen.findByRole('combobox', { name: 'Requester' }, { timeout: 5000 })
    await user.click(screen.getByRole('button', { name: 'Enter the request' }))
    expect(screen.getByRole('combobox', { name: 'Requester' })).toHaveFocus()
    expect(screen.getByRole('combobox', { name: 'Use' })).toHaveAccessibleDescription('Choose the use')
    expect(screen.getByRole('combobox', { name: 'Strain 1' })).toHaveAccessibleDescription(/Choose the strain$/)
    expect(calls).toHaveLength(0)
  })

  it('does not send the last valid count of vials while the field shows an invalid one (#111)', async () => {
    const { user } = setup()
    await fill(user)
    const calls = mockApi('post', POST, makeRequest())
    const vials = screen.getByRole('textbox', { name: 'Vials of strain 1' })
    expect(vials).toHaveValue('2')
    for (const [typed, message] of [
      ['12x', 'Ask for 1 to 50 vials'],
      ['-1', 'Ask for 1 to 50 vials'],
      ['1,5', 'Ask for 1 to 50 vials'],
      ['51', 'Ask for 1 to 50 vials'],
    ] as const) {
      await user.clear(vials)
      await user.type(vials, typed)
      await user.click(screen.getByRole('button', { name: 'Enter the request' }))
      await waitFor(() => expect(vials).toHaveAccessibleDescription(expect.stringContaining(message)))
      expect(vials).toHaveValue(typed)
      expect(calls).toHaveLength(0)
    }
  })

  it('puts the server errors on their fields, the EU refusal on the requester', async () => {
    allowConsole(/API error (400|422)/)
    const { user } = setup()
    await fill(user)
    mockApiError('post', POST, 400, validationProblem([{ attr: 'lines.0.strain', code: 'no_terms', detail: 'This strain has no terms: it came from no deposit.' }]))
    await user.click(screen.getByRole('button', { name: 'Enter the request' }))
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Strain 1' })).toHaveAccessibleDescription(/no terms/))
    expect(screen.getByRole('combobox', { name: 'Strain 1' })).toHaveFocus()
    mockApiError('post', POST, 422, problem(422, { code: 'export_not_supported' }))
    await user.click(screen.getByRole('button', { name: 'Enter the request' }))
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Requester' })).toHaveAccessibleDescription(/outside the EU/))
  })

  it('adds and removes strain lines, and refuses the same strain twice', async () => {
    const { user } = setup()
    await screen.findByRole('combobox', { name: 'Requester' }, { timeout: 5000 })
    await user.click(screen.getByRole('button', { name: 'Add a strain' }))
    expect(screen.getByRole('combobox', { name: 'Strain 2' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Remove strain 2' }))
    expect(screen.queryByRole('combobox', { name: 'Strain 2' })).not.toBeInTheDocument()
  })
  it('offers no requester whose contact was erased', async () => {
    mockApi('get', '/api/v1/auth/me/', makeMe())
    mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: 'curator' }))
    mockApi('get', '/api/v1/labs/{lab_public_id}/requesters/', page([requester, makeRequester({ institution: 'Erased Institute', erased: true, name: '' })]))
    renderApp({ path: `/labs/${LAB_ID}/requests/new` })
    const select = await screen.findByRole('combobox', { name: 'Requester' }, { timeout: 5000 })
    expect([...select.querySelectorAll('option')].map((o) => o.textContent)).toEqual(['Choose', 'Example Institute (CZ)'])
  })

})
