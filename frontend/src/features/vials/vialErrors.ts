import { errorMessage, isApiError } from '@/lib/api'

/** The message a form owns for a failure, by the problem code; never the server's own text. */
export function vialError(error: unknown): string {
  if (isApiError(error, 409) && error.code === 'position_taken') return 'Another vial is in this position. Choose another one.'
  if (isApiError(error, 409) && error.code === 'vial_not_in_collection') return 'This vial has left the collection or is lost. Reload to see it.'
  if (isApiError(error, 409) && error.code === 'strain_not_active') return 'The strain is not active: nothing is grown or preserved from it.'
  if (isApiError(error, 409) && (error.code === 'batch_number_taken' || error.code === 'vial_placed_meanwhile'))
    return 'Someone changed this at the same moment. Reload and try again.'
  if (isApiError(error, 403) && error.code === 'location_grant_required') return "Only people the lab's managers named may see where regulated strains are."
  return errorMessage(error)
}
