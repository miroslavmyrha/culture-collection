import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { allowConsole } from '@/test/console'
import { makeListMatch, makeStrainDisagreement, makeStrainRow, page } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { ListDisagreements } from './ListDisagreements'

const LAB_ID = '00000000-0000-4000-8000-00000000000a'
const LIST = '/api/v1/labs/{lab_public_id}/strains/list-disagreements/'
const STRAIN_ID = '00000000-0000-4000-8000-0000000000d1'
const PARAMS = { limit: 25, offset: 0 }

const render = () => renderWithProviders(<ListDisagreements labId={LAB_ID} params={PARAMS} onOffsetChange={() => undefined} />)

describe('ListDisagreements', () => {
  it('says what each disagreement is and names the entry it was read in', async () => {
    mockApi(
      'get',
      LIST,
      page([
        makeStrainDisagreement({
          strain: makeStrainRow({ public_id: STRAIN_ID, accession_number: 'MYC 42', risk_group: 2 }),
          findings: [
            { disagreement: 'restriction_missing', restriction_kind: 'dual_use', entry: makeListMatch({ code: '1C351.c.99' }), accepted_because: '' },
            { disagreement: 'restriction_unlisted', restriction_kind: 'cz_rat', entry: null, accepted_because: '' },
            { disagreement: 'risk_group_differs', restriction_kind: '', entry: makeListMatch({ list: 'cz-361-2007-annex-7', act: '361/2007', code: '1.99', risk_group: 3, restriction_kind: '' }), accepted_because: 'Recorded as group 2 after the lab test.' },
          ],
        }),
      ]),
    )
    await render()
    const row = within(await screen.findByRole('table', { name: 'Classification check' })).getByRole('row', { name: /MYC 42/ })
    expect(row).toHaveTextContent('The list names a restriction the strain does not carry: Dual-use item (2021/821, entry 1C351.c.99')
    expect(row).toHaveTextContent('The strain carries a restriction no entry names: Risky agent (RAT).')
    expect(row).toHaveTextContent('Annex 7 states another risk group: the entry states risk group 3, the strain has 2')
    expect(row).toHaveTextContent('Accepted by the collection: Recorded as group 2 after the lab test.')
    expect(within(row).getByRole('link', { name: 'MYC 42' })).toHaveAttribute('href', `/labs/${LAB_ID}/strains/${STRAIN_ID}`)
  })

  it('says so when nothing disagrees', async () => {
    mockApi('get', LIST, page([]))
    await render()
    expect(await screen.findByText('No strain of this lab disagrees with the official lists.')).toBeInTheDocument()
  })

  it('offers a retry when the check cannot be read', async () => {
    allowConsole(/API error 500/)
    mockApiError('get', LIST, 500)
    await render()
    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
