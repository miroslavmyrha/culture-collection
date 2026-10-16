import { type ReactNode, useId } from 'react'

export type FieldControlProps = { id: string; 'aria-invalid': boolean; 'aria-describedby': string | undefined }

type Props = {
  label: string
  error?: string
  hint?: string
  /** Render prop, so it works with register() and with Controller. Spread the props on the input. */
  children: (control: FieldControlProps) => ReactNode
}

/**
 * Owns the label, hint and error ids. The error is described, not announced: no role="alert" per
 * field, the form shows one form-level alert and focus moves to the first invalid field.
 */
export function Field({ label, error, hint, children }: Props) {
  const id = useId()
  const hintId = `${id}-hint`
  const errorId = `${id}-error`
  const describedBy = [hint ? hintId : '', error ? errorId : ''].filter(Boolean).join(' ') || undefined
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children({ id, 'aria-invalid': Boolean(error), 'aria-describedby': describedBy })}
      {hint && <p id={hintId}>{hint}</p>}
      {error && <p id={errorId}>{error}</p>}
    </div>
  )
}
