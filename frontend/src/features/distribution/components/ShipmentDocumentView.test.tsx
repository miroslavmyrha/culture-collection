import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeLab, makeMe, makeShipmentDocument, problem } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const DOCUMENT_ID = '00000000-0000-4000-8000-0000000000e1'
const REQUEST_ID = '00000000-0000-4000-8000-0000000000a1'
const DOCUMENT = '/api/v1/labs/{lab_public_id}/shipment-documents/{public_id}/'
const TEXT = 'DELIVERY NOTE\n\nShipment: 1\nRequest: 2026/7\n\nCONTENTS\n\n1. Strain MYC 3, Mockia vulgaris\n'

function signedIn(role: 'viewer' | 'curator' = 'curator') {
  mockApi('get', '/api/v1/auth/me/', makeMe())
  mockApi('get', '/api/v1/labs/{public_id}/', makeLab({ public_id: LAB_ID, name: 'Mycology', my_role: role }))
}

const open = () => renderApp({ path: `/labs/${LAB_ID}/shipment-documents/${DOCUMENT_ID}` })
const note = makeShipmentDocument({ public_id: DOCUMENT_ID, request: REQUEST_ID, request_number: '2026/7', text: TEXT, text_sha256: 'a'.repeat(64) })

describe('a document of a shipment', { timeout: 20_000 }, () => {
  it('shows the text as it was sent with its SHA-256, a print button and a download', async () => {
    signedIn()
    mockApi('get', DOCUMENT, note)
    open()
    expect(await screen.findByRole('heading', { level: 1, name: 'Delivery note, request 2026/7' }, { timeout: 5000 })).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe('Delivery note, request 2026/7 | Culture collection'))
    expect(screen.getByLabelText('Document text').textContent).toBe(TEXT)
    expect(screen.getByText('a'.repeat(64))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download as text' })).toHaveAttribute('href', `${window.location.origin}/api/v1/labs/${LAB_ID}/shipment-documents/${DOCUMENT_ID}/download/`)
    expect(screen.getByRole('link', { name: 'Back to request 2026/7' })).toHaveAttribute('href', `/labs/${LAB_ID}/requests/${REQUEST_ID}`)
    const print = vi.spyOn(window, 'print').mockImplementation(() => undefined)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Print' }))
    expect(print).toHaveBeenCalledTimes(1)
    print.mockRestore()
  })

  it('names the line of a per-line document', async () => {
    signedIn()
    mockApi('get', DOCUMENT, makeShipmentDocument({ public_id: DOCUMENT_ID, kind: 'register_entry', strain: 'MYC 3', request_number: '2026/7' }))
    open()
    expect(await screen.findByRole('heading', { level: 1, name: 'Register entry and handover protocol for MYC 3, request 2026/7' }, { timeout: 5000 })).toBeInTheDocument()
  })

  it('says not found for a role that does not open documents, as the server answers 404', async () => {
    allowConsole(/404/)
    signedIn('viewer')
    mockApiError('get', DOCUMENT, 404, problem(404))
    open()
    expect(await screen.findByRole('heading', { level: 1, name: 'Document not found' }, { timeout: 5000 })).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe('Document not found | Culture collection'))
  })

  it('offers a retry when the document fails to load', async () => {
    allowConsole(/500/)
    signedIn()
    mockApiError('get', DOCUMENT, 500)
    open()
    expect(await screen.findByText(/Could not load the document/, {}, { timeout: 5000 })).toBeInTheDocument()
    mockApi('get', DOCUMENT, note)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByLabelText('Document text', {}, { timeout: 5000 })).toBeInTheDocument()
  })
})
