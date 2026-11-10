import { type ApiError, isApiError } from '@/lib/api'

/** A message, or a function of the error when the text carries data from it. */
export type ErrorMessage = string | ((error: ApiError) => string)

/**
 * A table of messages by problem code. The key is `status:code` when the status is part of the
 * match, or `*:code` for a code that matches at any status.
 */
export type ErrorTable = Readonly<Record<string, ErrorMessage>>

/** The message the table owns for this error, or undefined when it owns none. */
export function lookupError(table: ErrorTable, error: unknown): string | undefined {
  if (!isApiError(error) || error.code === undefined) return undefined
  const key = Object.hasOwn(table, `${error.status}:${error.code}`) ? `${error.status}:${error.code}` : `*:${error.code}`
  if (!Object.hasOwn(table, key)) return undefined
  const message = table[key]
  return typeof message === 'function' ? message(error) : message
}
