import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeMtaTemplate, makeTerms } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { StrainTerms } from './StrainTerms'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const DEPOSIT_ID = '00000000-0000-4000-8000-0000000000d2'
const TERMS = '/api/v1/labs/{lab_public_id}/strains/{public_id}/terms/'

const mta = makeMtaTemplate({ code: 'STD', version: 2, title: 'Standard MTA' })
const first = makeTerms({ version: 1, is_active: false, created_at: '2026-02-01T10:00:00Z', country_of_origin: 'CZ', collection_date: '2019-05' })
const second = makeTerms({
  version: 2,
  is_active: true,
  mta,
  created_at: '2026-05-01T10:00:00Z',
  reason: 'The depositor withdrew teaching.',
  abs_scope: 'in_scope',
  ircc: 'ABSCH-IRCC-XX-000000-1',
  mat_uses: ['research_noncommercial'],
  uses: [
    { use: 'research_noncommercial', decision: 'permit' },
    { use: 'teaching', decision: 'deny' },
  ],
})

const render = () => renderWithProviders(<StrainTerms labId={LAB_ID} strainId={STRAIN_ID} />)
/** A version's facts, label to value. */
const facts = (article: HTMLElement) => Object.fromEntries([...article.querySelectorAll('dt')].map((dt) => [dt.textContent, dt.nextElementSibling?.textContent]))

describe('StrainTerms', { timeout: 20_000 }, () => {
  it('shows every version, newest first, the one in force marked, with what each allowed', async () => {
    mockApi('get', TERMS, { deposit: null, versions: [second, first] })
    await render()
    const versions = await screen.findAllByRole('article')
    expect(versions.map((v) => within(v).getByRole('heading', { level: 3 }).textContent)).toEqual(['Version 2 In force', 'Version 1 Replaced'])
    expect(facts(screen.getByRole('article', { name: 'Version 2' }))).toEqual({
      Valid: 'in force since 2026-05-01',
      'Why it replaced the one before': 'The depositor withdrew teaching.',
      MTA: 'MTA STD version 2, Standard MTA',
      'ABS (Regulation 511/2014)': 'In scope',
      'Country of origin': 'Not recorded',
      'Collection date': 'Not recorded',
      'Certificate of compliance (IRCC)': 'ABSCH-IRCC-XX-000000-1',
      'Uses the MAT covers': 'Non-commercial research',
    })
    expect(facts(screen.getByRole('article', { name: 'Version 1' }))).toMatchObject({ Valid: 'from 2026-02-01 to 2026-05-01', MTA: 'No MTA.', 'Country of origin': 'Czechia', 'Collection date': '2019-05' })
    const uses = screen.getByRole('table', { name: 'Uses of version 2' })
    expect(within(uses).getAllByRole('row').slice(1).map((row) => row.textContent)).toEqual(['Non-commercial researchPermitted', 'TeachingNot permitted'])
    expect(screen.getByText('2 versions, newest first.')).toBeInTheDocument()
  })

  it('links the deposit and the MTA only when the server names the deposit (deposits.view)', async () => {
    mockApi('get', TERMS, { deposit: null, versions: [second] })
    const viewer = await render()
    await screen.findAllByRole('article')
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    viewer.unmount()
    mockApi('get', TERMS, { deposit: DEPOSIT_ID, versions: [second] })
    await render()
    expect(await screen.findByRole('link', { name: 'Open the deposit' })).toHaveAttribute('href', `/labs/${LAB_ID}/deposits/${DEPOSIT_ID}`)
    expect(screen.getByRole('link', { name: 'MTA STD version 2, Standard MTA' })).toHaveAttribute('href', `/labs/${LAB_ID}/mta-templates/${mta.public_id}`)
  })

  it('says when there are no terms, and shows a failed read with a retry', async () => {
    allowConsole(/API error 500/)
    mockApi('get', TERMS, { deposit: null, versions: [] })
    const empty = await render()
    expect(await screen.findByText('No terms of use are recorded: the strain came from no deposit.')).toBeInTheDocument()
    empty.unmount()
    mockApiError('get', TERMS, 500)
    await render()
    expect(await screen.findByText(/Could not load the terms/)).toBeInTheDocument()
    mockApi('get', TERMS, { deposit: null, versions: [second] })
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('article', { name: 'Version 2' })).toBeInTheDocument()
  })
})
