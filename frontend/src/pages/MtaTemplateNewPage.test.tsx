import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeLab, makeMe, makeMtaTemplate } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const LAB = '/api/v1/labs/{public_id}/'
const LIST = '/api/v1/labs/{lab_public_id}/mta-templates/'
const ONE = '/api/v1/labs/{lab_public_id}/mta-templates/{public_id}/'
const version = makeMtaTemplate({ code: 'STD', version: 2, title: 'Standard MTA', text: 'Line one.' })

function signedIn(role: 'manager' | 'curator') {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', LAB, makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}

const path = `/labs/${LAB_ID}/mta-templates/new`

describe('MtaTemplateNewPage', () => {
  it('tells a member who is no manager that only managers publish', async () => {
    signedIn('curator')
    renderApp({ path })
    expect(await screen.findByText('Only managers publish MTA versions.', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Code' })).not.toBeInTheDocument()
  })

  it('starts the form from the version it was told to start from', async () => {
    signedIn('manager')
    mockApi('get', ONE, version)
    renderApp({ path, search: { from: version.public_id } })
    expect(await screen.findByRole('textbox', { name: 'Text' }, { timeout: 5000 })).toHaveValue('Line one.')
  })

  it('says the version to start from did not load, and offers to try again', async () => {
    allowConsole(/API error 500/)
    signedIn('manager')
    mockApiError('get', ONE, 500)
    renderApp({ path, search: { from: version.public_id } })
    expect(await screen.findByText(/Could not load the version to start from/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('opens the published version', async () => {
    signedIn('manager')
    mockApi('post', LIST, version)
    mockApi('get', ONE, version)
    const { router } = renderApp({ path })
    const user = userEvent.setup()
    await user.type(await screen.findByRole('textbox', { name: 'Code' }), 'std')
    await user.type(screen.getByRole('textbox', { name: 'Title' }), 'Standard MTA')
    await user.type(screen.getByRole('textbox', { name: 'Text' }), 'Line one.')
    await user.click(screen.getByRole('button', { name: 'Publish the version' }))
    await waitFor(() => expect(router.state.location.pathname).toBe(`/labs/${LAB_ID}/mta-templates/${version.public_id}`))
  })
})
