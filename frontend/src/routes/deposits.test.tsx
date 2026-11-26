import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { makeLab, makeMe, page } from '@/test/factories'
import { mockApi } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const signedIn = () => mockApi('get', '/api/v1/auth/me/', makeMe())

// The MTA templates are read by curators and managers only (#65): the loaders ask for them only
// when the caller's role may read them, so a viewer's page sends no request the API would refuse.
describe.each([`/labs/${LAB_ID}/mta-templates`, `/labs/${LAB_ID}/deposits/new`])('%s', (path) => {
  it("asks a viewer's browser for no MTA template", async () => {
    signedIn()
    mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: 'viewer' }))
    const templates = mockApi('get', '/api/v1/labs/{lab_public_id}/mta-templates/', page([]))
    renderApp({ path })
    expect((await screen.findAllByText(/Mycology/)).length).toBeGreaterThan(0)
    expect(templates).toHaveLength(0)
  })

  it('loads them once for a curator, before the page renders', async () => {
    signedIn()
    mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: 'curator' }))
    const templates = mockApi('get', '/api/v1/labs/{lab_public_id}/mta-templates/', page([]))
    renderApp({ path })
    expect((await screen.findAllByText(/Mycology/)).length).toBeGreaterThan(0)
    expect(templates).toHaveLength(1)
  })
})
