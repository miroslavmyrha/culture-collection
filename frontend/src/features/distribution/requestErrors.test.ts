import { describe, expect, it } from 'vitest'
import { ApiError } from '@/lib/api'
import { SECOND_PERSON, STATE_ERRORS, stateError } from './requestErrors'

/** Every message as it was written before the lookup table, by status and code. */
const EXPECTED: [string, string, string][] = [
  ['409', 'request_state', 'The request changed meanwhile. Close this and look at it again.'],
  ['409', 'not_enough_vials', 'Fewer vials are free than the request asks for. Close this and look at it again.'],
  ['409', 'vial_reserved_meanwhile', 'A vial was reserved at the same moment. Try again.'],
  ['422', 'request_blocked', 'Something blocks the approval now. Close this and read what stands in the way.'],
  ['403', 'manager_approval_required', 'A manager approves this request.'],
  ['422', 'second_person_required', SECOND_PERSON],
  ['422', 'ship_in_one_step', 'No strain of this request is regulated: close this and ship it in one step.'],
  ['403', 'confirm_own_approval', 'You approved this request, so a different person confirms its shipment.'],
  ['403', 'confirm_own_preparation', 'You prepared this shipment, so a different person confirms it.'],
  ['409', 'preparation_changed', 'The prepared shipment changed meanwhile. Close this and read it again.'],
  ['409', 'preparation_exists', 'Someone prepared this shipment at the same moment. Close this and look at it again.'],
]

const answer = (status: number, code: string, detail?: string) => new ApiError(status, { code, detail })

describe('stateError', () => {
  it.each(EXPECTED)('answers %s %s with its message', (status, code, message) => {
    expect(stateError(answer(Number(status), code))).toBe(message)
  })

  it('builds the shipment_blocked message from the problem detail', () => {
    expect(stateError(answer(422, 'shipment_blocked', 'Box 3 is out of service.'))).toBe('Nothing is shipped. Box 3 is out of service.')
    expect(stateError(answer(422, 'shipment_blocked'))).toBe('Nothing is shipped.')
  })

  it('has exactly the keys the messages above need', () => {
    const keys = [...EXPECTED.map(([status, code]) => `${status}:${code}`), '422:shipment_blocked']
    expect(Object.keys(STATE_ERRORS).toSorted()).toEqual(keys.toSorted())
  })

  it('keeps the two-person text shared with the request page', () => {
    expect(SECOND_PERSON).toContain('A regulated strain leaves in two steps')
  })

  it('does not answer a code at another status', () => {
    for (const [status, code] of [...EXPECTED, ['422', 'shipment_blocked', '']] as [string, string, string][]) {
      expect(stateError(answer(Number(status) === 418 ? 419 : 418, code))).toBeUndefined()
    }
  })

  it('has no message for an unknown code, a bare status or a plain error', () => {
    expect(stateError(answer(409, 'no_such_code'))).toBeUndefined()
    expect(stateError(new ApiError(409, undefined))).toBeUndefined()
    expect(stateError(new Error('boom'))).toBeUndefined()
    expect(stateError(answer(409, 'constructor'))).toBeUndefined()
  })
})
