import userEvent from '@testing-library/user-event'
import { beforeAll, describe, expect, it } from 'vitest'
import { permitSchema } from './schemas'

// jsdom has no DataTransfer: a FileList comes from a file input that a user filled.
let files: FileList | null = null
beforeAll(async () => {
  const input = document.createElement('input')
  input.type = 'file'
  document.body.append(input)
  await userEvent.setup().upload(input, new File(['%PDF-1.4'], 'permit.pdf', { type: 'application/pdf' }))
  files = input.files
  input.remove()
})
const file = () => files
const permit = (overrides: Record<string, unknown> = {}) => ({
  kind: 'sujb_rat_notice',
  issuer: 'SÚJB',
  issuer_country: 'CZ',
  reference: 'DEV/1',
  valid_from: '2026-01-01',
  expires_on: '',
  covers: '',
  quantity_allowed: '',
  sendings_allowed: '',
  gmo_category: '',
  risk_group: '',
  file: file(),
  ...overrides,
})
const issues = (value: unknown) => {
  const result = permitSchema.safeParse(value)
  return result.success ? [] : result.error.issues.map((issue) => issue.path.join('.'))
}

describe('the permit form', () => {
  it('asks a VRAT permit, an exception and a Letter of Authority for what they name, as on the document', () => {
    for (const kind of ['sujb_vrat', 'sujb_exception', 'plant_health_loa']) expect(issues(permit({ kind }))).toContain('covers')
    expect(issues(permit({ kind: 'sujb_vrat', covers: 'Mockia vulgaris' }))).toEqual([])
    expect(issues(permit())).toEqual([])
  })

  it('asks a letter for its quantity and sendings, a GMO authorisation for its category, a work permit for its risk group', () => {
    expect(issues(permit({ kind: 'plant_health_loa', covers: 'Mockia vulgaris' }))).toEqual(['quantity_allowed', 'sendings_allowed'])
    expect(issues(permit({ kind: 'gmo_contained_use' }))).toEqual(['gmo_category'])
    expect(issues(permit({ kind: 'pathogen_work_permit' }))).toEqual(['risk_group'])
  })

  it('needs the file', () => {
    expect(issues(permit({ file: null }))).toEqual(['file'])
  })
})
