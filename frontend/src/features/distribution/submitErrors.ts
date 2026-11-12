import type { FieldValues, Path, UseFormSetError } from 'react-hook-form'
import { errorMessage, isApiError } from '@/lib/api'
import { type ErrorTable, lookupError } from '@/lib/errorTable'
import { applyServerErrors } from '@/lib/forms'
import { STATE_ERRORS } from './requestErrors'

/**
 * What a dialog shows when its submit failed: the table's message for the problem code, else the
 * server's field errors put into the form, else the generic message for the status. Undefined
 * when the errors landed on fields, so the dialog has no banner of its own.
 */
export function submitFailure<T extends FieldValues>(error: unknown, fields: readonly Path<T>[], setError: UseFormSetError<T>, table: ErrorTable = {}): string | undefined {
  return lookupError(table, error) ?? (applyServerErrors(error, fields, setError) ? undefined : errorMessage(error))
}

/** Answers of a dialog on top of the request's own state errors. */
const withState = (own: ErrorTable): ErrorTable => ({ ...STATE_ERRORS, ...own })

export const ACCEPTANCE_ERRORS = withState({ '409:acceptance_exists': 'An acceptance of this MTA version is recorded already.' })
export const ANSWER_ERRORS = withState({ '409:depositor_answer_exists': 'The depositor’s answer for this strain is recorded already. Close this and look at it again.' })
export const REQUESTER_ERRORS: ErrorTable = { '409:contact_erased': 'This contact was erased. The requester can no longer be changed.' }
export const END_PERMIT_ERRORS: ErrorTable = { '409:permit_ended': 'This permit was ended already.' }

const MISSING_REASON = { type: 'server', message: 'Say why' } as const

/**
 * The failure of a decision with a reason: a missing reason lands on the field and is focused,
 * the request's state errors and the field errors come as in submitFailure.
 */
export function reasonFailure(error: unknown, setError: UseFormSetError<{ reason: string }>): string | undefined {
  if (isApiError(error) && error.code === 'reason_required') {
    setError('reason', MISSING_REASON, { shouldFocus: true })
    return undefined
  }
  return submitFailure(error, ['reason'], setError, STATE_ERRORS)
}
