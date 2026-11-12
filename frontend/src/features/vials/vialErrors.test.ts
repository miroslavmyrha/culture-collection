import { describe, expect, it } from 'vitest'
import { ApiError, errorMessage } from '@/lib/api'
import { entryError, gridError, POSITION_TAKEN, VIAL_ERRORS, vialError } from './vialErrors'

/** Every message as it was written before the lookup table, by status ('*' for any) and code. */
const EXPECTED: [string, string, string][] = [
  ['409', 'position_taken', POSITION_TAKEN],
  ['409', 'vial_not_in_collection', 'This vial has left the collection or is lost. Reload to see it.'],
  ['409', 'strain_not_active', 'The strain is not active: nothing is grown or preserved from it.'],
  ['409', 'batch_number_taken', 'Someone changed this at the same moment. Reload and try again.'],
  ['409', 'vial_placed_meanwhile', 'Someone changed this at the same moment. Reload and try again.'],
  ['409', 'vial_not_available', 'This vial is not available any more. Choose another one, or none.'],
  ['409', 'batch_exhausted', 'This batch is exhausted: it is not checked, released or held any more.'],
  ['409', 'check_entered_in_error', 'This check was entered in error already. Reload to see it.'],
  ['422', 'checks_not_passed', 'A batch is released once its latest identity, purity and viability checks passed. Reload to see its checks.'],
  ['409', 'transition_not_allowed', 'The batch changed meanwhile. Reload and try again.'],
  ['409', 'vial_not_lost', 'This vial was found meanwhile: there is no loss to report. Reload to see it.'],
  ['409', 'loss_changed', 'This vial was found and lost again since the page was loaded. Reload and record the report of the new loss.'],
  ['409', 'loss_reported', 'The report of this loss is recorded already. Reload to see it.'],
  ['409', 'loss_not_reportable', 'Its strain was not a highly risky or risky agent when the vial was lost: the act asks no report to the police.'],
  ['409', 'vial_not_to_destroy', 'A vial of the list is no longer marked to destroy. Reload and record again.'],
  ['409', 'vial_in_destruction', 'A vial of the list is in a record that waits for its confirmation already. Reload to see it.'],
  ['409', 'destruction_not_awaiting', 'This record waits for no confirmation any more: it was confirmed or entered in error. Reload to see it.'],
  ['409', 'destruction_outdated', "The strain's restrictions changed since the destruction was recorded. Enter this record in error and record the destruction again."],
  ['409', 'destruction_entered_in_error', 'This record was entered in error already. Reload to see it.'],
  ['403', 'confirm_own_destruction', 'You recorded this destruction: a different manager confirms it.'],
  ['400', 'witness_without_vrat_access', "This member was not on the lab's VRAT access list on the day of the destruction. A manager keeps that list on the lab page."],
  ['422', 'authorisation_method_missing', "The lab's ÚKZÚZ permit has no destruction method recorded here. Ask staff to record the permit again with the method its application declared."],
  ['403', 'location_grant_required', "Only people the lab's managers named may see where regulated strains are."],
]

const answer = (status: number, code: string) => new ApiError(status, { code })

describe('vialError', () => {
  it.each(EXPECTED)('answers %s %s with its message', (status, code, message) => {
    const statuses = status === '*' ? [400, 409, 422, 500] : [Number(status)]
    for (const s of statuses) expect(vialError(answer(s, code))).toBe(message)
  })

  it('has exactly the keys the messages above need', () => {
    expect(Object.keys(VIAL_ERRORS).toSorted()).toEqual(EXPECTED.map(([status, code]) => `${status}:${code}`).toSorted())
  })

  it('does not answer a code the table keeps for another status', () => {
    for (const [status, code] of EXPECTED.filter(([s]) => s !== '*')) {
      const other = answer(Number(status) === 418 ? 419 : 418, code)
      expect(vialError(other)).toBe(errorMessage(other))
    }
  })

  it('falls back to the generic message for an unknown code, a bare status and a plain error', () => {
    const unknown = answer(409, 'no_such_code')
    expect(vialError(unknown)).toBe(errorMessage(unknown))
    expect(vialError(unknown)).toBe('Someone else changed it. Reload and try again.')
    expect(vialError(new ApiError(409, undefined))).toBe('Someone else changed it. Reload and try again.')
    expect(vialError(new Error('boom'))).toBe('Something went wrong. Try again.')
  })

  it('does not read an inherited property as a code', () => {
    expect(vialError(answer(409, 'constructor'))).toBe('Someone else changed it. Reload and try again.')
  })
})

describe('gridError', () => {
  const OUT_OF_SERVICE = 'This box or a unit holding it is out of service or retired.'

  it.each([
    ['unit_not_active', OUT_OF_SERVICE],
    ['not_a_box', OUT_OF_SERVICE],
    ['risk_group_above_cap', "This box may not hold this strain's risk group."],
    ['outside_box', 'This position is not in the box. Reload the page.'],
  ])('answers %s at any status', (code, message) => {
    for (const status of [400, 409, 422]) expect(gridError(answer(status, code))).toBe(message)
  })

  it('leaves every other answer to the form messages', () => {
    expect(gridError(answer(409, 'position_taken'))).toBe(POSITION_TAKEN)
    expect(gridError(answer(409, 'no_such_code'))).toBe('Someone else changed it. Reload and try again.')
    expect(gridError(new Error('boom'))).toBe('Something went wrong. Try again.')
  })
})

describe('entryError', () => {
  it.each([
    ['position_taken', POSITION_TAKEN],
    ['position_twice', 'Another vial of the list goes to this position. Choose another one.'],
    ['vial_already_placed', 'This vial is in a box already. Move it from its own row.'],
    ['vial_not_in_collection', 'This vial has left the collection or is lost. Reload to see it.'],
    ['risk_group_above_cap', "This box may not hold this strain's risk group."],
    ['outside_box', 'This position is not in the box. Reload the page.'],
  ])('answers %s', (code, message) => {
    expect(entryError(code)).toBe(message)
  })

  it('says the vial could not be placed for an unknown or inherited code', () => {
    const fallback = 'This vial could not be placed. Reload the page and try again.'
    expect(entryError('no_such_code')).toBe(fallback)
    expect(entryError('')).toBe(fallback)
    expect(entryError('constructor')).toBe(fallback)
  })
})
