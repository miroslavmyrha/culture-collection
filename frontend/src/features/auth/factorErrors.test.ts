import { describe, expect, it } from 'vitest'
import { problem } from '@/test/factories'
import { ApiError } from '@/lib/api'
import { factorError, stepExpired } from './factorErrors'
import { tooManyAttempts } from './components/LoginForm'

const browser = (name: string) => Object.assign(new Error('refused'), { name })

describe('factorError', () => {
  it('names the wait after too many attempts', () => {
    expect(factorError(new ApiError(429, {}, { retryAfterMs: 120_000 }))).toBe(tooManyAttempts(120_000))
  })

  it('sends the user back to sign in when the password step ended', () => {
    expect(factorError(new ApiError(401, {}))).toBe('The sign-in took too long. Sign in again.')
    expect(stepExpired(new ApiError(401, {}))).toBe(true)
    expect(stepExpired(new ApiError(422, {}))).toBe(false)
  })

  it('asks for the second factor first on a step-up refusal, not on another 403', () => {
    expect(factorError(new ApiError(403, { code: 'step_up_required' }))).toBe('Confirm with your second factor first.')
    expect(factorError(new ApiError(403, { code: 'permission_denied' }))).toBe('That did not work. Try again.')
  })

  it.each([409, 422])("gives the server's own words (%i)", (status) => {
    expect(factorError(new ApiError(status, problem(status, { detail: 'That code was used already.' })))).toBe('That code was used already.')
  })

  it("does not show a server error's text", () => {
    expect(factorError(new ApiError(500, problem(500, { detail: 'Traceback (most recent call last)' })))).toBe('That did not work. Try again.')
  })

  it.each(['NotAllowedError', 'AbortError'])('says the key did not answer (%s)', (name) => {
    expect(factorError(browser(name))).toBe('The security key did not answer. Try again, or use another way.')
  })

  it('says a key is added already', () => {
    expect(factorError(browser('InvalidStateError'))).toBe('This security key is added already.')
  })

  it('falls back for any other failure', () => {
    expect(factorError(browser('TypeError'))).toBe('That did not work. Try again.')
    expect(factorError('not an error')).toBe('That did not work. Try again.')
  })
})
