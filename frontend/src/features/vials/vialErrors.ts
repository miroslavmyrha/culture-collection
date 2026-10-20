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
