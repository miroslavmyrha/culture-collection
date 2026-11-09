import { readProblem } from '@/lib/api'
import { type ErrorTable, lookupError } from '@/lib/errorTable'

/** How a regulated request leaves (ADR 0009, the two-person rule). */
export const SECOND_PERSON = 'A regulated strain leaves in two steps: one person prepares the shipment, and a second person, neither the approver nor the preparer, confirms it.'

/** A request that failed because someone else acted first, or the policy stopped it, by status and problem code. */
export const STATE_ERRORS: ErrorTable = {
  '409:request_state': 'The request changed meanwhile. Close this and look at it again.',
  '409:not_enough_vials': 'Fewer vials are free than the request asks for. Close this and look at it again.',
  '409:vial_reserved_meanwhile': 'A vial was reserved at the same moment. Try again.',
  '422:request_blocked': 'Something blocks the approval now. Close this and read what stands in the way.',
  '403:manager_approval_required': 'A manager approves this request.',
  '422:second_person_required': SECOND_PERSON,
  '422:ship_in_one_step': 'No strain of this request is regulated: close this and ship it in one step.',
  '422:shipment_blocked': (error) => `Nothing is shipped. ${readProblem(error.body)?.detail ?? ''}`.trim(),
  '403:confirm_own_approval': 'You approved this request, so a different person confirms its shipment.',
  '403:confirm_own_preparation': 'You prepared this shipment, so a different person confirms it.',
  '409:preparation_changed': 'The prepared shipment changed meanwhile. Close this and read it again.',
  '409:preparation_exists': 'Someone prepared this shipment at the same moment. Close this and look at it again.',
}

/** A request that failed because someone else acted first, or the policy stopped it. */
export function stateError(error: unknown): string | undefined {
  return lookupError(STATE_ERRORS, error)
}
