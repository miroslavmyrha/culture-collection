import { isApiError, readProblem } from '@/lib/api'
import { tooManyAttempts } from './components/LoginForm'

const OWN_WORDS = new Set([409, 422])

/** What a failed second-factor step says (#176). 401: the password step ended, sign in again. */
export function factorError(error: unknown): string {
  if (isApiError(error, 429)) return tooManyAttempts(error.retryAfterMs)
  if (isApiError(error, 401)) return 'The sign-in took too long. Sign in again.'
  if (isApiError(error, 403) && error.code === 'step_up_required') return 'Confirm with your second factor first.'
  const detail = isApiError(error) && OWN_WORDS.has(error.status) ? readProblem(error.body)?.detail : undefined
  if (detail) return detail
  return browserRefusal(error) ?? 'That did not work. Try again.'
}

/** The browser's own refusal: the user cancelled, the key timed out or is not for this site. */
function browserRefusal(error: unknown): string | undefined {
  if (!(error instanceof Error)) return undefined
  if (error.name === 'NotAllowedError' || error.name === 'AbortError') return 'The security key did not answer. Try again, or use another way.'
  if (error.name === 'InvalidStateError') return 'This security key is added already.'
  return undefined
}

/** The password step is over: back to the sign-in form. */
export const stepExpired = (error: unknown) => isApiError(error, 401)
