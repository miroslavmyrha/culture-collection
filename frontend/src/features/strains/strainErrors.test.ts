import { describe, expect, it } from 'vitest'
import { ApiError, errorMessage } from '@/lib/api'
import { PERMIT_REFUSED, RISK_GROUP_4_REFUSED, RISK_GROUP_ABOVE_BOX_CAP, RISK_GROUP_STEP_TOO_BIG, STRAIN_ERRORS, strainError } from './strainErrors'

/** Every message as it was written before the lookup table, by status ('*' for any) and code. */
const EXPECTED: [string, string, string][] = [
  ['422', 'lab_authorisation_required', PERMIT_REFUSED],
  ['*', 'risk_group_4_refused', RISK_GROUP_4_REFUSED],
  ['*', 'risk_group_above_box_cap', RISK_GROUP_ABOVE_BOX_CAP],
  ['409', 'accession_taken', 'Another strain took this number at the same moment. Save again.'],
  ['409', 'restriction_ended', 'This restriction has ended already. Reload to see it.'],
  ['409', 'end_proposed', 'Someone has proposed to end this restriction already. Close this and look at it again.'],
  ['409', 'end_not_proposed', 'The proposal changed meanwhile. Close this and read it again before you decide.'],
  ['409', 'end_proposal_changed', 'The proposal changed meanwhile. Close this and read it again before you decide.'],
  ['403', 'confirm_own_end_proposal', 'You proposed to end this restriction: a different manager confirms it.'],
  ['409', 'strain_deaccessioned', 'This strain has left the collection already. Reload to see it.'],
  ['422', 'second_person_required', 'This strain is regulated now: close this and propose the deaccession, a manager other than you confirms it.'],
  ['422', 'deaccession_in_one_step', 'This strain is no longer regulated: close this and deaccession it in one step.'],
  ['409', 'deaccession_proposed', 'Someone has proposed to deaccession this strain already. Close this and look at it again.'],
  ['409', 'deaccession_not_proposed', 'The proposal changed meanwhile. Close this and read it again before you decide.'],
  ['409', 'deaccession_proposal_changed', 'The proposal changed meanwhile. Close this and read it again before you decide.'],
  ['409', 'deaccession_proposal_outdated', "The strain's restrictions changed since the proposal. Withdraw it and propose the deaccession again."],
  ['409', 'request_awaits_confirmation', 'A shipment of this strain waits for its second person. Withdraw the prepared shipment on its request first, then deaccession the strain.'],
  ['403', 'confirm_own_deaccession', 'You proposed to deaccession this strain: a different manager confirms it.'],
  ['*', 'risk_group_step_too_big', RISK_GROUP_STEP_TOO_BIG],
  ['422', 'risk_group_second_person_required', 'A lower risk group is not set in one step: close this and propose it, a manager other than you confirms it.'],
  ['422', 'risk_group_not_lower', 'This is not a lower risk group: close this and change it in one step.'],
  ['409', 'risk_group_proposed', "Someone has proposed to lower this strain's risk group already. Close this and look at it again."],
  ['409', 'risk_group_not_proposed', 'The proposal changed meanwhile. Close this and read it again before you decide.'],
  ['409', 'risk_group_proposal_changed', 'The proposal changed meanwhile. Close this and read it again before you decide.'],
  ['409', 'risk_group_proposal_outdated', "The strain's risk group changed since the proposal. Withdraw it and propose again."],
  ['403', 'confirm_own_risk_group', 'You proposed this risk group: a different manager confirms it.'],
]

const answer = (status: number, code: string) => new ApiError(status, { code })

describe('strainError', () => {
  it.each(EXPECTED)('answers %s %s with its message', (status, code, message) => {
    const statuses = status === '*' ? [400, 409, 422, 500] : [Number(status)]
    for (const s of statuses) expect(strainError(answer(s, code))).toBe(message)
  })

  it('has exactly the keys the messages above need', () => {
    expect(Object.keys(STRAIN_ERRORS).toSorted()).toEqual(EXPECTED.map(([status, code]) => `${status}:${code}`).toSorted())
  })

  it('does not answer a code the table keeps for another status', () => {
    for (const [status, code] of EXPECTED.filter(([s]) => s !== '*')) {
      const other = answer(Number(status) === 418 ? 419 : 418, code)
      expect(strainError(other)).toBe(errorMessage(other))
    }
  })

  it('falls back to the generic message for an unknown code, a bare status and a plain error', () => {
    const unknown = answer(409, 'no_such_code')
    expect(strainError(unknown)).toBe(errorMessage(unknown))
    expect(strainError(unknown)).toBe('Someone else changed it. Reload and try again.')
    expect(strainError(new ApiError(409, undefined))).toBe('Someone else changed it. Reload and try again.')
    expect(strainError(new Error('boom'))).toBe('Something went wrong. Try again.')
  })

  it('does not read an inherited property as a code', () => {
    expect(strainError(answer(409, 'constructor'))).toBe('Someone else changed it. Reload and try again.')
  })
})
