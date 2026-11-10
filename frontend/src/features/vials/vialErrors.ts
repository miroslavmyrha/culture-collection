import { errorMessage, isApiError } from '@/lib/api'
import { type ErrorTable, lookupError } from '@/lib/errorTable'

/** A taken position says only that it is taken, never by what (ADR 0009). */
export const POSITION_TAKEN = 'Another vial is in this position. Choose another one.'

/** The message the form owns for a failure, by status and problem code. */
export const VIAL_ERRORS: ErrorTable = {
  '409:position_taken': POSITION_TAKEN,
  '409:vial_not_in_collection': 'This vial has left the collection or is lost. Reload to see it.',
  '409:strain_not_active': 'The strain is not active: nothing is grown or preserved from it.',
  '409:batch_number_taken': 'Someone changed this at the same moment. Reload and try again.',
  '409:vial_placed_meanwhile': 'Someone changed this at the same moment. Reload and try again.',
  '409:vial_not_available': 'This vial is not available any more. Choose another one, or none.',
  '409:batch_exhausted': 'This batch is exhausted: it is not checked, released or held any more.',
  '409:check_entered_in_error': 'This check was entered in error already. Reload to see it.',
  '422:checks_not_passed': 'A batch is released once its latest identity, purity and viability checks passed. Reload to see its checks.',
  '409:transition_not_allowed': 'The batch changed meanwhile. Reload and try again.',
  '409:vial_not_lost': 'This vial was found meanwhile: there is no loss to report. Reload to see it.',
  '409:loss_changed': 'This vial was found and lost again since the page was loaded. Reload and record the report of the new loss.',
  '409:loss_reported': 'The report of this loss is recorded already. Reload to see it.',
  '409:loss_not_reportable': 'Its strain was not a highly risky or risky agent when the vial was lost: the act asks no report to the police.',
  '409:vial_not_to_destroy': 'A vial of the list is no longer marked to destroy. Reload and record again.',
  '409:vial_in_destruction': 'A vial of the list is in a record that waits for its confirmation already. Reload to see it.',
  '409:destruction_not_awaiting': 'This record waits for no confirmation any more: it was confirmed or entered in error. Reload to see it.',
  '409:destruction_outdated': "The strain's restrictions changed since the destruction was recorded. Enter this record in error and record the destruction again.",
  '409:destruction_entered_in_error': 'This record was entered in error already. Reload to see it.',
  '403:confirm_own_destruction': 'You recorded this destruction: a different manager confirms it.',
  '400:witness_without_vrat_access': "This member was not on the lab's VRAT access list on the day of the destruction. A manager keeps that list on the lab page.",
  '422:authorisation_method_missing': "The lab's ÚKZÚZ permit has no destruction method recorded here. Ask staff to record the permit again with the method its application declared.",
  '403:location_grant_required': "Only people the lab's managers named may see where regulated strains are.",
}

/** The message a form owns for a failure, by the problem code; never the server's own text. */
export function vialError(error: unknown): string {
  return lookupError(VIAL_ERRORS, error) ?? errorMessage(error)
}

/**
 * The message the box grid announces for a refused place or move, by the problem code. A taken
 * position says only that it is taken, never by what (ADR 0009).
 */
export function gridError(error: unknown): string {
  if (isApiError(error) && (error.code === 'unit_not_active' || error.code === 'not_a_box')) return 'This box or a unit holding it is out of service or retired.'
  if (isApiError(error) && error.code === 'risk_group_above_cap') return "This box may not hold this strain's risk group."
  if (isApiError(error) && error.code === 'outside_box') return 'This position is not in the box. Reload the page.'
  return vialError(error)
}

/**
 * The message for a refusal of one vial among several placed at once (#77), by its code. It
 * names no position or box beyond what the person chose (ADR 0009).
 */
export function entryError(code: string): string {
  switch (code) {
    case 'position_taken':
      return POSITION_TAKEN
    case 'position_twice':
      return 'Another vial of the list goes to this position. Choose another one.'
    case 'vial_already_placed':
      return 'This vial is in a box already. Move it from its own row.'
    case 'vial_not_in_collection':
      return 'This vial has left the collection or is lost. Reload to see it.'
    case 'risk_group_above_cap':
      return "This box may not hold this strain's risk group."
    case 'outside_box':
      return 'This position is not in the box. Reload the page.'
    default:
      return 'This vial could not be placed. Reload the page and try again.'
  }
}
