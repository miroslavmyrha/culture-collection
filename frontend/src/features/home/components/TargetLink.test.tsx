import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test/render'
import { TargetLink } from './TargetLink'

const LAB = '00000000-0000-4000-8000-0000000000ba'
const ID = '00000000-0000-4000-8000-0000000000d1'
const VIAL = '00000000-0000-4000-8000-0000000000a9'

describe('TargetLink', () => {
  it.each([
    ['lab', null, null, `/labs/${LAB}`],
    ['permits', null, null, `/labs/${LAB}/permits`],
    ['requesters', null, null, `/labs/${LAB}/requesters`],
    ['deposit', ID, null, `/labs/${LAB}/deposits/${ID}`],
    ['request', ID, null, `/labs/${LAB}/requests/${ID}`],
    ['storage_unit', ID, null, `/labs/${LAB}/storage/${ID}`],
    ['mta_template', ID, null, `/labs/${LAB}/mta-templates/${ID}`],
    ['strain', ID, null, `/labs/${LAB}/strains/${ID}`],
    ['strain', ID, VIAL, `/labs/${LAB}/strains/${ID}/material?vial=${VIAL}`],
  ] as const)('links a %s target with id %s and vial %s to its page', async (target, id, vial, href) => {
    await renderWithProviders(
      <TargetLink labId={LAB} target={target} id={id} vial={vial}>
        Where it is
      </TargetLink>,
    )
    expect(screen.getByRole('link', { name: 'Where it is' })).toHaveAttribute('href', href)
  })

  it.each([
    [null, ID],
    ['deposit', null],
    ['strain', null],
  ] as const)('renders the words alone for target %s with id %s', async (target, id) => {
    await renderWithProviders(
      <TargetLink labId={LAB} target={target} id={id}>
        Words only
      </TargetLink>,
    )
    expect(screen.getByText('Words only')).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })
})
