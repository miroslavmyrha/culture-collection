import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeLab, page } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { LabList } from './LabList'

const PARAMS = { limit: 25, offset: 0 }

describe('LabList', () => {
  it('shows loading, then my labs with my role and a link to each', async () => {
    const lab = makeLab({ name: 'Mycology', code: 'MYC', my_role: 'curator' })
    mockApi('get', '/api/v1/labs/', page([lab]))
    await renderWithProviders(<LabList params={PARAMS} onOffsetChange={vi.fn<(offset: number) => void>()} />)
    expect(screen.getByText('Loading your labs…')).toBeInTheDocument()
    const link = await screen.findByRole('link', { name: 'Mycology' })
    expect(link).toHaveAttribute('href', `/labs/${lab.public_id}`)
    const row = screen.getByRole('row', { name: /Mycology/ })
    expect(row).toHaveTextContent('MYC')
    expect(row).toHaveTextContent('Curator')
  })

  it('says so when I am in no lab', async () => {
    mockApi('get', '/api/v1/labs/', page([]))
    await renderWithProviders(<LabList params={PARAMS} onOffsetChange={vi.fn<(offset: number) => void>()} />)
    expect(await screen.findByText(/You are not a member of any lab yet/)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows a failure with a retry that works', async () => {
    allowConsole(/API error 500/)
    mockApiError('get', '/api/v1/labs/', 500)
    await renderWithProviders(<LabList params={PARAMS} onOffsetChange={vi.fn<(offset: number) => void>()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load your labs. The server failed. Try again in a moment.')
    mockApi('get', '/api/v1/labs/', page([makeLab({ name: 'Back again' })]))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('link', { name: 'Back again' })).toBeInTheDocument()
  })

  it('offers the first page past the end', async () => {
    mockApi('get', '/api/v1/labs/', page([], { count: 3 }))
    const onOffsetChange = vi.fn<(offset: number) => void>()
    await renderWithProviders(<LabList params={{ limit: 25, offset: 50 }} onOffsetChange={onOffsetChange} />)
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Go to the first page' }))
    expect(onOffsetChange).toHaveBeenCalledWith(0)
  })
})
