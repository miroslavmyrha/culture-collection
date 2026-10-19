import { errorMessage, isApiError } from '@/lib/api'

/** The message a form owns for a failure, by the problem code; never the server's own text. */
export function storageError(error: unknown): string {
  if (isApiError(error, 409) && error.code === 'unit_retired') return 'This unit is retired and changes no more. Reload to see it.'
  if (isApiError(error, 422) && error.code === 'unit_not_empty') return 'The unit still holds units that are not retired. Move or retire them first.'
  return errorMessage(error)
}
