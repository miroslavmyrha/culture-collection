import { errorMessage, isApiError, readProblem } from '@/lib/api'

/** The server's own words for a refused reset (409, 422, 400), else the general message. */
export function resetError(error: unknown): string {
  const detail = isApiError(error) && [400, 409, 422].includes(error.status) ? readProblem(error.body)?.detail : undefined
  return detail ?? errorMessage(error)
}
