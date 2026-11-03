import { errorMessage, isApiError } from '@/lib/api'

/** A taken position says only that it is taken, never by what (ADR 0009). */
export const POSITION_TAKEN = 'Another vial is in this position. Choose another one.'

/** The message a form owns for a failure, by the problem code; never the server's own text. */
export function vialError(error: unknown): string {
  if (isApiError(error, 409) && error.code === 'position_taken') return POSITION_TAKEN
  if (isApiError(error, 409) && error.code === 'vial_not_in_collection') return 'This vial has left the collection or is lost. Reload to see it.'
  if (isApiError(error, 409) && error.code === 'strain_not_active') return 'The strain is not active: nothing is grown or preserved from it.'
  if (isApiError(error, 409) && (error.code === 'batch_number_taken' || error.code === 'vial_placed_meanwhile'))
    return 'Someone changed this at the same moment. Reload and try again.'
  if (isApiError(error, 409) && error.code === 'vial_not_available') return 'This vial is not available any more. Choose another one, or none.'
  if (isApiError(error, 409) && error.code === 'batch_exhausted') return 'This batch is exhausted: it is not checked, released or held any more.'
  if (isApiError(error, 409) && error.code === 'check_entered_in_error') return 'This check was entered in error already. Reload to see it.'
  if (isApiError(error, 422) && error.code === 'checks_not_passed') return 'A batch is released once its latest identity, purity and viability checks passed. Reload to see its checks.'
  if (isApiError(error, 409) && error.code === 'transition_not_allowed') return 'The batch changed meanwhile. Reload and try again.'
  if (isApiError(error, 409) && error.code === 'vial_not_lost') return 'This vial was found meanwhile: there is no loss to report. Reload to see it.'
  if (isApiError(error, 409) && error.code === 'loss_changed') return 'This vial was found and lost again since the page was loaded. Reload and record the report of the new loss.'
  if (isApiError(error, 409) && error.code === 'loss_reported') return 'The report of this loss is recorded already. Reload to see it.'
  if (isApiError(error, 409) && error.code === 'loss_not_reportable') return 'Its strain was not a highly risky or risky agent when the vial was lost: the act asks no report to the police.'
  if (isApiError(error, 409) && error.code === 'vial_not_to_destroy') return 'A vial of the list is no longer marked to destroy. Reload and record again.'
  if (isApiError(error, 409) && error.code === 'vial_in_destruction') return 'A vial of the list is in a record that waits for its confirmation already. Reload to see it.'
  if (isApiError(error, 409) && error.code === 'destruction_not_awaiting') return 'This record waits for no confirmation any more: it was confirmed or entered in error. Reload to see it.'
  if (isApiError(error, 409) && error.code === 'destruction_outdated')
    return "The strain's restrictions changed since the destruction was recorded. Enter this record in error and record the destruction again."
  if (isApiError(error, 409) && error.code === 'destruction_entered_in_error') return 'This record was entered in error already. Reload to see it.'
  if (isApiError(error, 403) && error.code === 'confirm_own_destruction') return 'You recorded this destruction: a different manager confirms it.'
  if (isApiError(error, 400) && error.code === 'witness_without_vrat_access')
    return "This member was not on the lab's VRAT access list on the day of the destruction. A manager keeps that list on the lab page."
  if (isApiError(error, 422) && error.code === 'authorisation_method_missing')
    return "The lab's ÚKZÚZ permit has no destruction method recorded here. Ask staff to record the permit again with the method its application declared."
  if (isApiError(error, 403) && error.code === 'location_grant_required') return "Only people the lab's managers named may see where regulated strains are."
  return errorMessage(error)
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
