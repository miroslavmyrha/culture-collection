import { describe, expect, it } from 'vitest'
import { STATUS_LABELS as DEPOSIT } from '@/features/deposits/schemas'
import { STATUS_LABELS as REQUEST } from '@/features/distribution/schemas'
import { STATUS_LABELS } from '@/features/search/schemas'
import { STATUS_LABELS as STRAIN } from '@/features/strains/schemas'
import { VIAL_STATUS_LABELS as VIAL } from '@/features/vials/schemas'

// The search may not import the other features (lint boundaries), so it keeps its own copy of
// their status words (#76). A word changed on one side fails here.
describe('the status words of a search result', () => {
  it('are the words of each kind’s own pages', () => {
    expect(STATUS_LABELS).toEqual({ strain: STRAIN, vial: VIAL, deposit: DEPOSIT, request: REQUEST })
  })
})
