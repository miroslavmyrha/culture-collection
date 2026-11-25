import { errorMessage, isApiError } from '@/lib/api'

/** The message a medium dialog owns for a failure, by the problem code. */
export function mediumError(error: unknown): string {
  if (isApiError(error, 409) && error.code === 'medium_retired') return 'This medium is retired. Close this and reload the list.'
  return errorMessage(error)
}
