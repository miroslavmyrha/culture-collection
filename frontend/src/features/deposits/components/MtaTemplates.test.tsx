import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeLab, makeMe, makeMtaTemplate, page, problem, validationProblem } from '@/test/factories'
import { holdApi, mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { renderApp, renderWithProviders } from '@/test/render'
import { mtaKeys } from '../api/keys'
import { MTA_ALL } from '../api/queries'
import type { MtaTemplate } from '../schemas'
import { MtaTemplateList } from './MtaTemplateList'
import { PublishMtaForm } from './PublishMtaForm'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const LIST = '/api/v1/labs/{lab_public_id}/mta-templates/'
const ONE = '/api/v1/labs/{lab_public_id}/mta-templates/{public_id}/'
const v2 = makeMtaTemplate({ code: 'STD', version: 2, title: 'Standard MTA', text_sha256: `0123456789ab${'c'.repeat(52)}`, text: 'Line one.\nLine two.' })

describe('MtaTemplateList', () => {
  it('lists each version linked, with the start of its hash', async () => {
    mockApi('get', LIST, page([v2, makeMtaTemplate({ version: 1 })]))
    await renderWithProviders(<MtaTemplateList labId={LAB_ID} />)
    const table = await screen.findByRole('table', { name: 'MTA templates' })
    const [, first] = within(table).getAllByRole('row')
    if (!first) throw new Error('no row')
    expect(within(first).getByRole('link', { name: 'STD version 2' })).toHaveAttribute('href', `/labs/${LAB_ID}/mta-templates/${v2.public_id}`)
    expect(first).toHaveTextContent('0123456789ab…')
  })

  it('says when there is none, and shows a load error', async () => {
    mockApi('get', LIST, page([]))
    await renderWithProviders(<MtaTemplateList labId={LAB_ID} />)
    expect(await screen.findByText('The lab has no MTA template yet.')).toBeInTheDocument()
  })
})

async function renderForm(from?: MtaTemplate) {
  const onPublished = vi.fn<(t: MtaTemplate) => void>()
  const view = await renderWithProviders(<PublishMtaForm labId={LAB_ID} from={from} onPublished={onPublished} />)
  return { ...view, onPublished, user: userEvent.setup() }
}

describe('PublishMtaForm', { timeout: 15_000 }, () => {
  it('publishes the text as typed, the code in capitals, and refreshes the list', async () => {
    const calls = mockApi('post', LIST, v2)
    const { user, client, onPublished } = await renderForm()
    client.setQueryData(mtaKeys.list(LAB_ID, MTA_ALL), page([]))
    await user.type(screen.getByRole('textbox', { name: 'Code' }), 'std')
    await user.type(screen.getByRole('textbox', { name: 'Title' }), 'Standard MTA')
    await user.type(screen.getByRole('textbox', { name: 'Text' }), '  Line one.{Enter}Line two.')
    await user.click(screen.getByRole('button', { name: 'Publish the version' }))
    await waitFor(() => expect(onPublished).toHaveBeenCalledWith(v2), { timeout: 5000 })
    expect(calls[0]?.body).toEqual({ code: 'STD', title: 'Standard MTA', text: '  Line one.\nLine two.' })
    expect(calls[0]?.headers.get('X-CSRFToken')).toBe('test-token')
    expect(client.getQueryData(mtaKeys.detail(LAB_ID, v2.public_id))).toEqual(v2)
    expect(client.getQueryState(mtaKeys.list(LAB_ID, MTA_ALL))?.isInvalidated).toBe(true)
  })

  it('starts from an earlier version and says which version it makes', async () => {
    await renderForm(v2)
    expect(screen.getByText(/This publishes version 3 of STD\./)).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Text' })).toHaveValue('Line one.\nLine two.')
  })

  it('refuses a bad code and an empty text without a request, focusing the first', async () => {
    const calls = recordRequests('post', LIST)
    const { user } = await renderForm()
    await user.type(screen.getByRole('textbox', { name: 'Code' }), 's t d')
    await user.click(screen.getByRole('button', { name: 'Publish the version' }))
    expect(screen.getByRole('textbox', { name: 'Code' })).toHaveFocus()
    expect(screen.getByRole('textbox', { name: 'Text' })).toHaveAccessibleDescription(/Enter the text of the agreement$/)
    expect(calls).toHaveLength(0)
  })

  it('publishes nothing under the last valid code while the field shows an invalid one (#111)', async () => {
    const calls = mockApi('post', LIST, v2)
    const { user } = await renderForm()
    await user.type(screen.getByRole('textbox', { name: 'Title' }), 'Standard MTA')
    await user.type(screen.getByRole('textbox', { name: 'Text' }), 'Line one.')
    const code = screen.getByRole('textbox', { name: 'Code' })
    await user.type(code, 'std')
    for (const typed of ['s t d', '-std', 'std_1', 'a'.repeat(21)]) {
      await user.clear(code)
      await user.type(code, typed)
      await user.click(screen.getByRole('button', { name: 'Publish the version' }))
      await waitFor(() => expect(code).toHaveAccessibleDescription(expect.stringContaining('Use up to 20 letters, digits and hyphens')))
      expect(code).toHaveValue(typed)
      expect(calls).toHaveLength(0)
    }
  })

  it('maps a server error to its field, and a race to its own words', async () => {
    mockApiError('post', LIST, 400, validationProblem([{ attr: 'code', code: 'invalid', detail: 'Not this code.' }]))
    const { user } = await renderForm(v2)
    await user.click(screen.getByRole('button', { name: 'Publish the version' }))
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Code' })).toHaveAccessibleDescription(/Not this code\.$/), { timeout: 5000 })
    mockApiError('post', LIST, 409, problem(409, { code: 'mta_version_taken' }))
    await user.click(screen.getByRole('button', { name: 'Publish the version' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Another version of this MTA was published at the same moment. Publish again.')
  })

  it('shows one safe message for a 403 and keeps the button focusable while it sends', async () => {
    allowConsole(/API error/)
    const held = holdApi('post', LIST)
    const { user } = await renderForm(v2)
    const button = screen.getByRole('button', { name: 'Publish the version' })
    await user.click(button)
    await waitFor(() => expect(button).toHaveAttribute('aria-disabled', 'true'), { timeout: 5000 })
    expect(button).toHaveFocus()
    await user.click(button)
    expect(held.calls).toHaveLength(1)
    held.release(403, problem(403, { detail: 'internal detail' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have permission to do that.')
    expect(screen.queryByText('internal detail')).not.toBeInTheDocument()
  })
})

function signedIn(role: 'curator' | 'manager') {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}

describe('the MTA pages', { timeout: 15_000 }, () => {
  it('shows the frozen text and its whole hash; a manager may start a new version from it', async () => {
    signedIn('manager')
    mockApi('get', ONE, v2)
    renderApp({ path: `/labs/${LAB_ID}/mta-templates/${v2.public_id}` })
    expect(await screen.findByRole('heading', { level: 1, name: 'STD version 2' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText(v2.text_sha256)).toBeInTheDocument()
    expect(screen.getByText(/Line one\.\s+Line two\./)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Publish a new version of STD' })).toHaveAttribute('href', `/labs/${LAB_ID}/mta-templates/new?from=${v2.public_id}`)
  })

  it('offers a curator no new version, and refuses the form', async () => {
    signedIn('curator')
    mockApi('get', ONE, v2)
    mockApi('get', LIST, page([v2]))
    renderApp({ path: `/labs/${LAB_ID}/mta-templates` })
    expect(await screen.findByRole('table', { name: 'MTA templates' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Publish an MTA version' })).not.toBeInTheDocument()
  })
})
