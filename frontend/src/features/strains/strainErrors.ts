import { errorMessage, isApiError, readProblem } from '@/lib/api'
import { type ErrorTable, lookupError } from '@/lib/errorTable'

/** The permit a kind needs (ADR 0009), for the refusal the server sends. */
export const PERMIT_REFUSED = 'This lab holds no valid permit for this restriction. Staff record permits; until then the strain cannot be added with it.'
export const PERMIT_REFUSED_BY_KIND: Record<string, string> = {
  cz_vrat: 'This lab holds no valid SÚJB permit for highly risky agents (VRAT). Staff record the permit; until then the strain cannot be added with this restriction.',
  quarantine_pest:
    'This lab holds no valid ÚKZÚZ permit for quarantine pests. Staff record the permit; until then the strain cannot be added with this restriction.',
}
export const RISK_GROUP_4_REFUSED = 'The collection does not hold risk group 4 agents.'
/** #174: a raise states the basis of each step, so it goes one group at a time. */
export const RISK_GROUP_STEP_TOO_BIG = 'A risk group rises one step at a time: raise it by one, with its basis, then again.'
/** Names no box: where a regulated strain is stays masked (ADR 0009). */
export const RISK_GROUP_ABOVE_BOX_CAP = "A box holding this strain's vials does not allow this risk group. Move the vials first."

const PROPOSAL_CHANGED = 'The proposal changed meanwhile. Close this and read it again before you decide.'

/** The message the form owns for a failure, by status and problem code. */
export const STRAIN_ERRORS: ErrorTable = {
  '422:lab_authorisation_required': PERMIT_REFUSED,
  '*:risk_group_4_refused': RISK_GROUP_4_REFUSED,
  '*:risk_group_above_box_cap': RISK_GROUP_ABOVE_BOX_CAP,
  '409:accession_taken': 'Another strain took this number at the same moment. Save again.',
  '409:restriction_ended': 'This restriction has ended already. Reload to see it.',
  '409:end_proposed': 'Someone has proposed to end this restriction already. Close this and look at it again.',
  '409:end_not_proposed': PROPOSAL_CHANGED,
  '409:end_proposal_changed': PROPOSAL_CHANGED,
  '403:confirm_own_end_proposal': 'You proposed to end this restriction: a different manager confirms it.',
  '409:strain_deaccessioned': 'This strain has left the collection already. Reload to see it.',
  '422:second_person_required': 'This strain is regulated now: close this and propose the deaccession, a manager other than you confirms it.',
  '422:deaccession_in_one_step': 'This strain is no longer regulated: close this and deaccession it in one step.',
  '409:deaccession_proposed': 'Someone has proposed to deaccession this strain already. Close this and look at it again.',
  '409:deaccession_not_proposed': PROPOSAL_CHANGED,
  '409:deaccession_proposal_changed': PROPOSAL_CHANGED,
  '409:deaccession_proposal_outdated': "The strain's restrictions changed since the proposal. Withdraw it and propose the deaccession again.",
  '409:request_awaits_confirmation': 'A shipment of this strain waits for its second person. Withdraw the prepared shipment on its request first, then deaccession the strain.',
  '403:confirm_own_deaccession': 'You proposed to deaccession this strain: a different manager confirms it.',
  '*:risk_group_step_too_big': RISK_GROUP_STEP_TOO_BIG,
  '422:risk_group_second_person_required': 'A lower risk group is not set in one step: close this and propose it, a manager other than you confirms it.',
  '422:risk_group_not_lower': 'This is not a lower risk group: close this and change it in one step.',
  '409:risk_group_proposed': "Someone has proposed to lower this strain's risk group already. Close this and look at it again.",
  '409:risk_group_not_proposed': PROPOSAL_CHANGED,
  '409:risk_group_proposal_changed': PROPOSAL_CHANGED,
  '409:risk_group_proposal_outdated': "The strain's risk group changed since the proposal. Withdraw it and propose again.",
  '403:confirm_own_risk_group': 'You proposed this risk group: a different manager confirms it.',
}

/** The message a form owns for a failure, by the problem code; never the server's own text. */
export function strainError(error: unknown): string {
  return lookupError(STRAIN_ERRORS, error) ?? errorMessage(error)
}

/** The field a 422 names (`restrictions.1.kind`), if any. */
export function problemField(error: unknown): string | undefined {
  if (!isApiError(error)) return undefined
  return readProblem(error.body)?.errors?.find((e) => e.attr !== null)?.attr ?? undefined
}
