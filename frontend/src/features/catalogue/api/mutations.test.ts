import { describe, expect, it } from 'vitest'
import { ApiError } from '@/lib/api'
import { refusal } from './mutations'

const problem = (code: string) => ({ type: 'about:blank', title: 'Unprocessable Entity', status: 422, detail: `Words of ${code}.`, code, errors: [] })

describe('refusal', () => {
  it.each(['catalogue_refused', 'catalogue_changed', 'catalogue_has_errors', 'reason_required'])('shows the words of the import’s own %s', (code) => {
    expect(refusal(new ApiError(422, problem(code)))).toBe(`Words of ${code}.`)
  })

  it.each([
    ['another rule', new ApiError(422, problem('quarantine_blocked'))],
    ['another status', new ApiError(400, problem('catalogue_refused'))],
    ['no problem body', new ApiError(422, undefined)],
    ['not an API error', new Error('network')],
  ])('leaves %s to the general message', (_, error) => {
    expect(refusal(error)).toBeUndefined()
  })
})
