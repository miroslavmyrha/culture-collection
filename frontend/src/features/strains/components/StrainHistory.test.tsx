import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { page } from '@/test/factories'
import { holdApi, mockApi } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import type { HistoryLine } from '../schemas'
import { StrainHistory } from './StrainHistory'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const REQUEST_ID = '00000000-0000-4000-8000-0000000000f1'
const HISTORY = '/api/v1/labs/{lab_public_id}/strains/{public_id}/history/'

const line = (summary: string, overrides: Partial<HistoryLine> = {}): HistoryLine => ({
  occurred_at: '2026-10-23T12:05:00Z',
  actor: 'user:0b9a4c7e-1111-4222-8333-444455556666',
  summary,
  target: 'strain',
  target_id: STRAIN_ID,
  ...overrides,
})

/** The tab as the page drives it: the offset in the page's state (the URL there). */
function Harness({ limit = 25 }: { limit?: number }) {
  const [offset, setOffset] = useState(0)
  return <StrainHistory labId={LAB_ID} strainId={STRAIN_ID} page={{ limit, offset }} onOffsetChange={setOffset} />
}

describe('StrainHistory', { timeout: 20_000 }, () => {
  it('lists what happened, newest first, who did it by label, and links a request', async () => {
    const calls = mockApi(
      'get',
      HISTORY,
      page(
        [
          line('asked for vials in request 2026/3', { target: 'request', target_id: REQUEST_ID, actor: 'you' }),
          line('placed vial MYC 42 / 1 / 1', { occurred_at: '2026-10-22T08:00:00Z' }),
          line('accessioned MYC 42', { occurred_at: '2026-10-01T08:00:00Z', actor: 'command:seed_dev' }),
        ],
        { count: 3 },
      ),
    )
    await renderWithProviders(<Harness />)
    const list = await screen.findByRole('list', { name: 'History, newest first' })
    expect(within(list).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      '2026-10-23 12:05You asked for vials in request 2026/3',
      '2026-10-22 08:00user 0b9a4c7e placed vial MYC 42 / 1 / 1',
      '2026-10-01 08:00command:seed_dev accessioned MYC 42',
    ])
    expect(within(list).getByRole('link', { name: 'asked for vials in request 2026/3' })).toHaveAttribute('href', `/labs/${LAB_ID}/requests/${REQUEST_ID}`)
    // A line about the strain itself links nowhere: the reader is on its page.
    expect(within(list).getAllByRole('link')).toHaveLength(1)
    expect(screen.getByText('3 events, newest first.')).toBeInTheDocument()
    expect(calls[0]?.url.searchParams.get('limit')).toBe('25')
    expect(calls[0]?.url.searchParams.get('offset')).toBe('0')
    // One page holds them all: no pager.
    expect(screen.queryByRole('navigation', { name: 'Pages of the history' })).not.toBeInTheDocument()
  })

  it('pages with the count of every line, keeping the page on screen while the next loads', async () => {
    mockApi('get', HISTORY, page([line('preserved MYC 42 batch 3'), line('preserved MYC 42 batch 2')], { count: 3 }))
    await renderWithProviders(<Harness limit={2} />)
    const pager = await screen.findByRole('navigation', { name: 'Pages of the history' })
    expect(pager).toHaveTextContent('1 to 2 of 3')
    const held = holdApi('get', HISTORY)
    const user = userEvent.setup()
    const next = within(pager).getByRole('button', { name: 'Next' })
    await user.click(next)
    await waitFor(() => expect(held.calls).toHaveLength(1))
    expect(held.calls[0]?.url.searchParams.get('offset')).toBe('2')
    // The first page stays, Next waits for the second (aria-disabled keeps the focus on it).
    expect(screen.getByText('preserved MYC 42 batch 3')).toBeInTheDocument()
    expect(next).toHaveAttribute('aria-disabled', 'true')
    expect(within(pager).getByRole('button', { name: 'Previous' })).toHaveAttribute('aria-disabled', 'true')
    held.release(200, page([line('accessioned MYC 42')], { count: 3 }))
    expect(await screen.findByText('accessioned MYC 42')).toBeInTheDocument()
    expect(pager).toHaveTextContent('3 to 3 of 3')
  })

  it('says when nothing may be read, and offers the first page past the end', async () => {
    mockApi('get', HISTORY, page([], { count: 0 }))
    const empty = await renderWithProviders(<Harness />)
    expect(await screen.findByText('Nothing you may read has happened to the strain yet.')).toBeInTheDocument()
    empty.unmount()
    mockApi('get', HISTORY, page([], { count: 4 }))
    await renderWithProviders(<Harness />)
    expect(await screen.findByRole('button', { name: 'Go to the first page' })).toBeInTheDocument()
  })
})
