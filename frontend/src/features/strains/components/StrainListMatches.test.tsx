import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { type ListMatch, makeListMatch, makeStrain, makeTerms, problem } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { StrainOverview } from './StrainOverview'
import { StrainShell } from './StrainShell'

// What the official lists say about the strain's taxon (#169): a read. Each line says which
// reading of which list says it, and someone who manages strains can take a line into the
// dialog that records it, where the reason is still theirs to write. The entries below are
// invented, as are the taxa, so no real organism is shown with a status it does not have.

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const DETAIL = '/api/v1/labs/{lab_public_id}/strains/{public_id}/'
const TERMS = '/api/v1/labs/{lab_public_id}/strains/{public_id}/terms/'
const MATCHES = '/api/v1/labs/{lab_public_id}/strains/{public_id}/list-matches/'
const ADD = '/api/v1/labs/{lab_public_id}/strains/{public_id}/restrictions/'
const RISK_GROUP = '/api/v1/labs/{lab_public_id}/strains/{public_id}/risk-group/'

const strain = makeStrain({ public_id: STRAIN_ID, accession_number: 'MYC 42', risk_group: 1 })

const dualUse = makeListMatch({ public_id: '00000000-0000-4000-8000-0000000000e1' })

const riskGroup = makeListMatch({
  public_id: '00000000-0000-4000-8000-0000000000e2',
  list: 'cz-361-2007-annex-7',
  list_title: 'Government order 361/2007 Sb., Annex 7',
  act: '361/2007 Sb.',
  version: '/sb/2007/361/2026-09-01',
  version_date: '2026-09-01',
  code: '1.99',
  restriction_kind: '',
  suggests_act: '',
  risk_group: 3,
})

const page = (results: readonly ListMatch[]) => ({ count: results.length, next: null, previous: null, results: [...results] })

function render({ canManage = true } = {}) {
  mockApi('get', DETAIL, strain)
  mockApi('get', TERMS, { deposit: null, versions: [makeTerms()] })
  return renderWithProviders(
    <main>
      <StrainShell labId={LAB_ID} strainId={STRAIN_ID} canManage={canManage}>
        {(s) => <StrainOverview labId={LAB_ID} strain={s} canManage={canManage} canConfirm={false} />}
      </StrainShell>
    </main>,
  )
}

describe('the official lists on the strain page', () => {
  it('names the entry, the list and the reading it comes from', async () => {
    mockApi('get', MATCHES, page([dualUse, riskGroup]))
    await render()
    const section = within(await screen.findByRole('region', { name: 'Official lists' }))
    expect(await section.findByText('1C351.c.99')).toBeInTheDocument()
    expect(section.getByText(/2021\/821, 32025R2003 of 2025-09-08/)).toBeInTheDocument()
    expect(section.getByText(/States risk group 3/)).toBeInTheDocument()
  })

  it('says so when no entry names the taxon', async () => {
    mockApi('get', MATCHES, page([]))
    await render()
    expect(await screen.findByText('No entry of the official lists names this taxon.')).toBeInTheDocument()
  })

  it('records a suggested restriction with the entry filled in and a reason of the person', async () => {
    const user = userEvent.setup()
    mockApi('get', MATCHES, page([dualUse]))
    const added = mockApi('post', ADD, strain)
    await render()
    await user.click(await screen.findByRole('button', { name: 'Record Dual-use item' }))
    const dialog = within(await screen.findByRole('dialog', { name: 'Add a restriction to MYC 42' }))
    expect(dialog.getByLabelText('List entry')).toHaveValue('1C351.c.99')
    expect(dialog.getByLabelText('Act Annex I was read in')).toHaveValue('(EU) 2025/2003')
    await user.type(dialog.getByLabelText('Reason'), 'Read in Annex I.')
    await user.click(dialog.getByRole('button', { name: 'Add restriction' }))
    expect(added[0]?.body).toEqual({ kind: 'dual_use', reference: '1C351.c.99', act: '(EU) 2025/2003', gmo_category: null, reason: 'Read in Annex I.' })
  })

  it('offers a suggested risk group as the basis of a change', async () => {
    const user = userEvent.setup()
    mockApi('get', MATCHES, page([riskGroup]))
    await render()
    await user.click(await screen.findByRole('button', { name: 'Use as the risk group basis' }))
    const dialog = within(await screen.findByRole('dialog', { name: 'Change the risk group of MYC 42' }))
    expect(dialog.getByRole('combobox', { name: 'Risk group' })).toHaveValue('3')
    expect(dialog.getByLabelText('Basis')).toHaveValue('Mockia fictiva (361/2007 Sb., entry 1.99, /sb/2007/361/2026-09-01)')
    expect(dialog.getByLabelText('Reason')).toHaveValue('')
  })

  it('records the suggested group with the entry of the annex it rests on', async () => {
    const user = userEvent.setup()
    mockApi('get', MATCHES, page([riskGroup]))
    const raised = mockApi('post', RISK_GROUP, strain)
    await render()
    await user.click(await screen.findByRole('button', { name: 'Use as the risk group basis' }))
    const dialog = within(await screen.findByRole('dialog', { name: 'Change the risk group of MYC 42' }))
    await user.type(dialog.getByLabelText('Reason'), 'Read in annex 7.')
    await user.click(dialog.getByRole('button', { name: 'Save risk group' }))
    // #169: the group, the basis and the entry come from the line, the reason from the person.
    expect(raised[0]?.body).toEqual({
      risk_group: 3,
      basis: 'Mockia fictiva (361/2007 Sb., entry 1.99, /sb/2007/361/2026-09-01)',
      basis_entry: riskGroup.public_id,
      reason: 'Read in annex 7.',
    })
  })

  it('offers nothing to record to somebody who does not manage strains', async () => {
    mockApi('get', MATCHES, page([dualUse, riskGroup]))
    await render({ canManage: false })
    const section = within(await screen.findByRole('region', { name: 'Official lists' }))
    expect(await section.findByText('1C351.c.99')).toBeInTheDocument()
    expect(section.queryByRole('button')).not.toBeInTheDocument()
  })

  it('says a restriction the strain already has is there, and offers it no second time', async () => {
    const held = makeStrain({
      public_id: STRAIN_ID,
      accession_number: 'MYC 42',
      risk_group: 1,
      restriction_history: [
        {
          public_id: '00000000-0000-4000-8000-0000000000c9',
          kind: 'dual_use',
          reference: '1C351.c.99',
          act: '(EU) 2025/2003',
          gmo_category: null,
          created_at: '2026-11-01T10:00:00Z',
          ended_at: null,
          end_reason: '',
          end_proposal: null,
        },
      ],
    })
    mockApi('get', DETAIL, held)
    mockApi('get', TERMS, { deposit: null, versions: [makeTerms()] })
    mockApi('get', MATCHES, page([dualUse]))
    await renderWithProviders(
      <main>
        <StrainShell labId={LAB_ID} strainId={STRAIN_ID} canManage>
          {(s) => <StrainOverview labId={LAB_ID} strain={s} canManage canConfirm={false} />}
        </StrainShell>
      </main>,
    )
    const section = within(await screen.findByRole('region', { name: 'Official lists' }))
    expect(await section.findByText(/the strain has one/)).toBeInTheDocument()
    expect(section.queryByRole('button', { name: /^Record / })).not.toBeInTheDocument()
  })

  it('offers to try again when the lists cannot be read', async () => {
    allowConsole(/list-matches/)
    const user = userEvent.setup()
    mockApiError('get', MATCHES, 500, problem(500, { code: 'server_error' }))
    await render()
    expect(await screen.findByText(/Could not load the official lists\./)).toBeInTheDocument()
    mockApi('get', MATCHES, page([riskGroup]))
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('1.99')).toBeInTheDocument()
  })
})
