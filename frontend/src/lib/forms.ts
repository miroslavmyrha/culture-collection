import type { FieldValues, Path, UseFormSetError } from 'react-hook-form'
import { ApiError, readProblem } from './api'

/**
 * Puts a 400's errors into the form: known fields get setError (the first one is focused),
 * everything else (non_field_errors, detail, unknown or nested keys) becomes one root.server
 * message. Accepts problem details {errors: [{attr, code, detail}]} and DRF's {"field": ["msg"]}.
 * Returns false when nothing was mapped, so the caller shows its generic message.
 */
export function applyServerErrors<T extends FieldValues>(
  error: unknown,
  fields: readonly Path<T>[],
  setError: UseFormSetError<T>,
): boolean {
  if (!(error instanceof ApiError) || error.status !== 400) return false
  const names: readonly string[] = fields
  const isField = (key: string): key is Path<T> => names.includes(key)
  let focused = false
  const rest: string[] = []
  for (const [key, message] of serverMessages(error.body)) {
    if (key !== null && isField(key)) {
      setError(key, { type: 'server', message }, { shouldFocus: !focused })
      focused = true
    } else rest.push(message)
  }
  if (rest.length > 0) setError('root.server', { type: 'server', message: rest.join(' ') })
  return focused || rest.length > 0
}

/** [field or null, message] pairs, the first message per key. */
function serverMessages(body: unknown): [string | null, string][] {
  const problem = readProblem(body)
  if (problem?.errors) {
    const seen = new Set<string | null>()
    return problem.errors.flatMap((e): [string | null, string][] => {
      if (seen.has(e.attr)) return []
      seen.add(e.attr)
      return [[e.attr, e.detail]]
    })
  }
  if (problem?.detail) return [[null, problem.detail]]
  if (typeof body !== 'object' || body === null || Array.isArray(body)) return []
  return Object.entries(body).flatMap(([key, value]): [string | null, string][] => {
    if (typeof value === 'string') return [[key === 'detail' ? null : key, value]]
    if (Array.isArray(value) && typeof value[0] === 'string') return [[key, value[0]]]
    return [] // nested (field arrays): flatten to "items.1.qty" when a form needs it
  })
}
