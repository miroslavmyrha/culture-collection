import MuiTextField, { type TextFieldProps as MuiTextFieldProps } from '@mui/material/TextField'
import type { Ref } from 'react'

type Props = Omit<MuiTextFieldProps, 'error' | 'helperText' | 'inputRef' | 'ref' | 'label'> & {
  label: string
  /** The field's error message: marks the input invalid and becomes its description. */
  error?: string | undefined
  /** Help that stays visible, also next to an error. */
  hint?: string | undefined
  /** Lands on the <input>, so react-hook-form can focus the first invalid field. */
  ref?: Ref<HTMLInputElement>
}

/**
 * MUI TextField with our wiring: a label, a description (the hint, then the error) linked
 * through aria-describedby, and aria-invalid on error. The error is described, not announced:
 * the form shows one form-level alert and focus moves to the first invalid field.
 * Spread register('name') on it: its ref goes to the input, not to MUI's wrapper div.
 */
export function TextField({ error, hint, ref, ...props }: Props) {
  const description = [hint, error].filter(Boolean).join(' ')
  return (
    <MuiTextField {...props} inputRef={ref} error={error !== undefined} helperText={description === '' ? undefined : description} />
  )
}
