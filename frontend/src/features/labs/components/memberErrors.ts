import { errorMessage, isApiError } from '@/lib/api'

/** The messages a member dialog owns, by the problem code; never the server's own text. */
export function memberError(error: unknown): string {
  if (isApiError(error) && error.code === 'last_manager') return 'A lab needs at least one active manager. Make another member manager first.'
  if (isApiError(error) && error.code === 'grant_above_own_role') return 'You cannot change a role above your own.'
  if (isApiError(error) && error.code === 'already_granted') return 'This member may see regulated locations already. Reload to see it.'
  if (isApiError(error, 409) && error.code === 'grant_revoked') return 'This grant has been revoked already. Reload to see it.'
  return errorMessage(error)
}
