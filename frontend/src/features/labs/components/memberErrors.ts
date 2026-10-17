import { errorMessage, isApiError } from '@/lib/api'

/** The messages a member dialog owns, by the problem code; never the server's own text. */
export function memberError(error: unknown): string {
  if (isApiError(error) && error.code === 'last_manager') return 'A lab needs at least one manager. Make another member manager first.'
  if (isApiError(error) && error.code === 'grant_above_own_role') return 'You cannot change a role above your own.'
  return errorMessage(error)
}
