import type { Ref } from 'react'
import { TextField } from './TextField'

type Option = { value: string; label: string }

type Props = Omit<React.ComponentProps<typeof TextField>, 'select' | 'slotProps' | 'children' | 'ref'> & {
  options: readonly Option[]
  /** Lands on the <select>, so react-hook-form focuses it like any input. */
  ref?: Ref<HTMLSelectElement>
}

/**
 * A select on our TextField wiring (label, description, aria-invalid), always native: a
 * <select> works with register() as is, keeps the platform's keyboard and screen reader
 * behaviour, and needs no popup. MUI passes inputRef to the <select> for native selects
 * (@mui/material 9.5.0, NativeSelect/NativeSelectInput.js:216).
 */
export function SelectField({ options, ref, ...props }: Props) {
  return (
    <TextField {...props} select slotProps={{ select: { native: true } }} ref={ref}>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </TextField>
  )
}
