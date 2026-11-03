import { describe, expect, it } from 'vitest'
import { STATUS_LABELS as DEPOSIT } from '@/features/deposits/schemas'
import { STATUS_LABELS as REQUEST } from '@/features/distribution/schemas'
import { VIAL_STATE_WORDS } from '@/features/home/schemas'
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

// Home keeps the vial states in lower case for a sentence ("7 available, 1 reserved") and may not
// import the vials feature either.
describe('the vial states on Home', () => {
  it('are the words of the vials feature, in lower case', () => {
    const own = Object.fromEntries(Object.entries(VIAL).map(([state, label]) => [state, label.toLowerCase()]))
    expect(Object.fromEntries(VIAL_STATE_WORDS)).toEqual(own)
  })
})
