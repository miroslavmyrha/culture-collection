import type { UseFormSetError } from 'react-hook-form'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api'
import { ACCEPTANCE_ERRORS, ANSWER_ERRORS, END_PERMIT_ERRORS, reasonFailure, REQUESTER_ERRORS, submitFailure } from './submitErrors'

const setter = () => vi.fn<UseFormSetError<Record<string, string>>>()
const answer = (status: number, body: unknown) => new ApiError(status, body)
const fieldError = (attr: string, detail: string) => ({ code: 'invalid', errors: [{ attr, code: 'invalid', detail }] })

describe('submitFailure', () => {
  it('answers a conflict with the message the dialog owns', () => {
    const setError = setter()
    expect(submitFailure(answer(409, { code: 'acceptance_exists' }), ['mta'], setError, ACCEPTANCE_ERRORS)).toBe('An acceptance of this MTA version is recorded already.')
    expect(submitFailure(answer(409, { code: 'depositor_answer_exists' }), ['line'], setError, ANSWER_ERRORS)).toBe(
      'The depositor’s answer for this strain is recorded already. Close this and look at it again.',
    )
    expect(submitFailure(answer(409, { code: 'contact_erased' }), ['name'], setError, REQUESTER_ERRORS)).toBe('This contact was erased. The requester can no longer be changed.')
    expect(submitFailure(answer(409, { code: 'permit_ended' }), ['reason'], setError, END_PERMIT_ERRORS)).toBe('This permit was ended already.')
    expect(setError).not.toHaveBeenCalled()
  })

  it('keeps the own answer to its own status', () => {
    expect(submitFailure(answer(422, { code: 'permit_ended' }), ['reason'], setter(), END_PERMIT_ERRORS)).toBe('The request was rejected. Check the form and try again.')
  })

  it('adds the request state errors to the answers of the dialogs that record against a request', () => {
    expect(submitFailure(answer(409, { code: 'request_state' }), ['mta'], setter(), ACCEPTANCE_ERRORS)).toBe('The request changed meanwhile. Close this and look at it again.')
    expect(submitFailure(answer(409, { code: 'request_state' }), ['line'], setter(), ANSWER_ERRORS)).toBe('The request changed meanwhile. Close this and look at it again.')
    expect(submitFailure(answer(409, { code: 'request_state' }), ['name'], setter(), REQUESTER_ERRORS)).toBe('Someone else changed it. Reload and try again.')
  })

  it('puts field errors on their fields and shows no banner', () => {
    const setError = setter()
    expect(submitFailure(answer(400, fieldError('signer_name', 'Enter who signed')), ['signer_name'], setError)).toBeUndefined()
    expect(setError).toHaveBeenCalledWith('signer_name', { type: 'server', message: 'Enter who signed' }, { shouldFocus: true })
  })

  it('falls back to the generic message of the status', () => {
    expect(submitFailure(answer(500, undefined), ['mta'], setter())).toBe('The server failed. Try again in a moment.')
    expect(submitFailure(new Error('boom'), ['mta'], setter())).toBe('Something went wrong. Try again.')
  })
})

describe('reasonFailure', () => {
  it('lands a missing reason on the reason field, focused, without a banner', () => {
    const setError = setter()
    expect(reasonFailure(answer(400, { code: 'reason_required' }), setError)).toBeUndefined()
    expect(setError).toHaveBeenCalledWith('reason', { type: 'server', message: 'Say why' }, { shouldFocus: true })
  })

  it('shows the request state errors as a banner', () => {
    const setError = setter()
    expect(reasonFailure(answer(409, { code: 'request_state' }), setError)).toBe('The request changed meanwhile. Close this and look at it again.')
    expect(setError).not.toHaveBeenCalled()
  })

  it('puts a field error of the reason on the field', () => {
    const setError = setter()
    expect(reasonFailure(answer(400, fieldError('reason', 'Too long')), setError)).toBeUndefined()
    expect(setError).toHaveBeenCalledWith('reason', { type: 'server', message: 'Too long' }, { shouldFocus: true })
  })

  it('falls back to the generic message', () => {
    expect(reasonFailure(answer(500, undefined), setter())).toBe('The server failed. Try again in a moment.')
  })
})
