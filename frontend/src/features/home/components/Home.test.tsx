import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeActivityLine, makeMyLab, makeOverview, makeWaitingGroup, makeWaitingItem } from '@/test/factories'
import { holdApi, mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { Home } from './Home'

const OVERVIEW = '/api/v1/me/overview/'
const ACTIVITY = '/api/v1/me/activity/'
const BAC = '00000000-0000-4000-8000-0000000000ba'
const MYC = '00000000-0000-4000-8000-0000000000c1'
const DEPOSIT = '00000000-0000-4000-8000-0000000000d1'
const REQUEST = '00000000-0000-4000-8000-0000000000e1'
const STRAIN = '00000000-0000-4000-8000-0000000000f1'

const curatorLab = makeMyLab({
  public_id: BAC,
  name: 'Bacteriology',
  code: 'BAC',
  role: 'curator',
  strains: 30,
  batches: { pending_check: 1, released: 3, on_hold: 0, exhausted: 0 },
  vials_available: 18,
  free_positions: 449,
  open_requests: 4,
  requests_to_decide: 2,
  deposits_to_check: 1,
  actions: ['receive_deposit', 'record_check', 'find_vial', 'enter_request'],
})
const viewerLab = makeMyLab({ public_id: MYC, name: 'Mycology', code: 'MYC', role: 'viewer', strains: 13 })

const section = (name: string) => screen.getByRole('region', { name })
const noActivity = () => mockApi('get', ACTIVITY, { results: [] })

describe('Home', () => {
  it('shows loading, then what waits with what, which lab, since when and why, linked to where it is handled', async () => {
    const held = holdApi('get', OVERVIEW)
    noActivity()
    await renderWithProviders(<Home />)
    expect(screen.getByText('Loading what waits for you…')).toBeInTheDocument()
    held.release(200, makeOverview({
      labs: [curatorLab],
      waiting: [
        makeWaitingGroup({ kind: 'deposit_received', items: [makeWaitingItem({ lab: BAC, subject: 'Testella exempli DEP-3', target: 'deposit', target_id: DEPOSIT, since: '2026-10-05' })] }),
        makeWaitingGroup({
          kind: 'request_to_decide',
          total: 25,
          items: [makeWaitingItem({ lab: BAC, subject: 'Request 2026/1, Example Institute', reason: 'A regulated strain: a manager approves it', target: 'request', target_id: REQUEST, needs_manager: true })],
        }),
        makeWaitingGroup({ kind: 'lab_permit_expiring', items: [makeWaitingItem({ lab: BAC, subject: 'SÚJB DEV/VRAT/7', target: 'lab', target_id: null, due: '2026-11-05' })] }),
      ],
    }))
    const waiting = await screen.findByRole('region', { name: 'Waiting for you (27)' })
    const deposits = within(waiting).getByRole('region', { name: 'Deposits received (1)' })
    expect(within(deposits).getByRole('link', { name: 'Testella exempli DEP-3' })).toHaveAttribute('href', `/labs/${BAC}/deposits/${DEPOSIT}`)
    expect(deposits).toHaveTextContent('BAC')
    expect(deposits).toHaveTextContent('Since 2026-10-05')
    expect(deposits).toHaveTextContent('Received, not checked yet')
    const requests = within(waiting).getByRole('region', { name: 'Requests to decide (25)' })
    expect(within(requests).getByRole('link', { name: 'Request 2026/1, Example Institute' })).toHaveAttribute('href', `/labs/${BAC}/requests/${REQUEST}`)
    expect(requests).toHaveTextContent('Manager approves')
    expect(requests).toHaveTextContent('The oldest 1 of 25 are shown.')
    const permits = within(waiting).getByRole('region', { name: 'Lab permits expiring (1)' })
    expect(permits).toHaveTextContent('Expires 2026-11-05')
    expect(within(permits).getByRole('link', { name: 'SÚJB DEV/VRAT/7' })).toHaveAttribute('href', `/labs/${BAC}`)
  })

  it('says nothing waits, and shows each lab with its role and figures linked to their lists', async () => {
    mockApi('get', OVERVIEW, makeOverview({ labs: [curatorLab, viewerLab] }))
    noActivity()
    await renderWithProviders(<Home />)
    expect(await screen.findByText('Nothing waits for you.')).toBeInTheDocument()
    const bac = within(section('My labs')).getByRole('article', { name: 'Bacteriology' })
    expect(bac).toHaveTextContent('BAC · Curator')
    expect(bac).toHaveTextContent('1 pending check, 3 released')
    expect(within(bac).getByRole('link', { name: 'Strains: 30' })).toHaveAttribute('href', `/labs/${BAC}/strains`)
    expect(within(bac).getByRole('link', { name: 'Free box positions: 449' })).toHaveAttribute('href', `/labs/${BAC}/storage`)
    expect(within(bac).getByRole('link', { name: 'Open requests: 4' })).toHaveAttribute('href', `/labs/${BAC}/requests`)
    expect(within(bac).getByRole('link', { name: 'Requests to decide: 2' })).toHaveAttribute('href', `/labs/${BAC}/requests?status=submitted`)
    expect(within(bac).getByRole('link', { name: 'Deposits to check: 1' })).toHaveAttribute('href', `/labs/${BAC}/deposits`)
    // The viewer's lab: what a viewer may not count is absent, not zero.
    const myc = within(section('My labs')).getByRole('article', { name: 'Mycology' })
    expect(myc).toHaveTextContent('MYC · Viewer')
    expect(myc).toHaveTextContent('BatchesNone')
    expect(within(myc).queryByRole('link', { name: /Requests to decide|Deposits to check/ })).not.toBeInTheDocument()
  })

  it('offers the actions of the roles, once per lab where there are several', async () => {
    const tech = makeMyLab({ public_id: MYC, code: 'MYC', role: 'technician', actions: ['record_check', 'find_vial'] })
    mockApi('get', OVERVIEW, makeOverview({ labs: [curatorLab, tech] }))
    noActivity()
    await renderWithProviders(<Home />)
    const actions = await screen.findByRole('region', { name: 'Quick actions' })
    const names = within(actions).getAllByRole('link').map((link) => [link.textContent, link.getAttribute('href')])
    expect(names).toEqual([
      ['Receive a deposit', `/labs/${BAC}/deposits/new`],
      ['Record a check in BAC', `/labs/${BAC}/strains`],
      ['Record a check in MYC', `/labs/${MYC}/strains`],
      ['Find a vial in BAC', `/labs/${BAC}/strains`],
      ['Find a vial in MYC', `/labs/${MYC}/strains`],
      ['Enter a request', `/labs/${BAC}/requests/new`],
    ])
  })

  it('shows a viewer no actions', async () => {
    mockApi('get', OVERVIEW, makeOverview({ labs: [viewerLab] }))
    noActivity()
    await renderWithProviders(<Home />)
    expect(await screen.findByRole('region', { name: 'My labs' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Quick actions' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Receive a deposit|Record a check|Find a vial|Enter a request/ })).not.toBeInTheDocument()
  })

  it('tells a person in no lab what to do', async () => {
    mockApi('get', OVERVIEW, makeOverview())
    noActivity()
    await renderWithProviders(<Home />)
    expect(await screen.findByText(/You are not a member of any lab yet/)).toBeInTheDocument()
    expect(screen.getByText('Nothing has happened in your labs yet.')).toBeInTheDocument()
  })

  it('shows the activity newest first, the actor by label or as You, linked to the subject', async () => {
    mockApi('get', OVERVIEW, makeOverview({ labs: [curatorLab] }))
    mockApi('get', ACTIVITY, {
      results: [
        makeActivityLine({ lab: BAC, lab_code: 'BAC', actor: 'you', summary: 'set BAC 29 batch 3 to released', target: 'strain', target_id: STRAIN, occurred_at: '2026-10-23T12:05:00Z' }),
        makeActivityLine({ lab: BAC, lab_code: 'BAC', actor: 'user:1c870e86-fe96-4324-8705-cbbbb8ef0cfa', summary: 'added a member', target: 'lab', target_id: null }),
        makeActivityLine({ lab: BAC, lab_code: 'BAC', actor: 'command:seed_dev', summary: 'generated a shipment document', target: null, target_id: null }),
      ],
    })
    await renderWithProviders(<Home />)
    const list = await screen.findByRole('list', { name: 'Recent activity, newest first' })
    const [first, second, third] = within(list).getAllByRole('listitem')
    expect(first).toHaveTextContent(/^2026-10-23 \d\d:05BACYou set BAC 29 batch 3 to released$/)
    expect(within(first!).getByRole('link', { name: 'set BAC 29 batch 3 to released' })).toHaveAttribute('href', `/labs/${BAC}/strains/${STRAIN}`)
    expect(first!.querySelector('time')).toHaveAttribute('datetime', '2026-10-23T12:05:00Z')
    expect(second).toHaveTextContent('user 1c870e86 added a member')
    expect(within(second!).getByRole('link', { name: 'added a member' })).toHaveAttribute('href', `/labs/${BAC}`)
    expect(third).toHaveTextContent('command:seed_dev generated a shipment document')
    expect(within(third!).queryByRole('link')).not.toBeInTheDocument()
  })

  it('shows a failed overview with a retry that works, and the activity beside it', async () => {
    allowConsole(/API error 500/)
    mockApiError('get', OVERVIEW, 500)
    mockApi('get', ACTIVITY, { results: [makeActivityLine({ summary: 'accessioned MYC 7' })] })
    await renderWithProviders(<Home />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load what waits for you. The server failed. Try again in a moment.')
    expect(await screen.findByText('accessioned MYC 7')).toBeInTheDocument()
    mockApi('get', OVERVIEW, makeOverview({ labs: [curatorLab] }))
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Nothing waits for you.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows a failed activity with a retry that works, and the rest of Home beside it', async () => {
    allowConsole(/API error 500/)
    mockApi('get', OVERVIEW, makeOverview({ labs: [curatorLab] }))
    mockApiError('get', ACTIVITY, 500)
    await renderWithProviders(<Home />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the activity. The server failed. Try again in a moment.')
    expect(screen.getByText('Nothing waits for you.')).toBeInTheDocument()
    mockApi('get', ACTIVITY, { results: [makeActivityLine({ summary: 'accessioned MYC 8' })] })
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('accessioned MYC 8')).toBeInTheDocument()
  })
})
