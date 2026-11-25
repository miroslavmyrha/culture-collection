import { describe, expect, it } from 'vitest'
import { problem } from '@/test/factories'
import { ApiError, errorMessage } from '@/lib/api'
import { resetError } from './resetErrors'

describe('resetError', () => {
  it.each([400, 409, 422])("gives the server's words for a refused reset (%i)", (status) => {
    expect(resetError(new ApiError(status, problem(status, { detail: 'Another manager confirms a reset you proposed.' })))).toBe(
      'Another manager confirms a reset you proposed.',
    )
  })

  it('falls back to the general message without words of its own', () => {
    const refused = new ApiError(409, {})
    expect(resetError(refused)).toBe(errorMessage(refused))
  })

  it('does not show the words of another status', () => {
    const failed = new ApiError(500, problem(500, { detail: 'Traceback (most recent call last)' }))
    expect(resetError(failed)).toBe(errorMessage(failed))
  })
})
