import Checkbox from '@mui/material/Checkbox'
import FormControlLabel from '@mui/material/FormControlLabel'
import type { ComponentProps, Ref } from 'react'

type Props = Omit<ComponentProps<typeof Checkbox>, 'slotProps' | 'ref'> & {
  label: string
  /** Lands on the <input>, so react-hook-form reads and focuses it like any input. */
  ref?: Ref<HTMLInputElement>
}

/**
 * A labelled checkbox. Spread register('name') on it with a `value`: several boxes with one
 * name give react-hook-form an array of the checked values. MUI's ref would land on the
 * wrapper span, so the ref goes to the input slot (@mui/material 9.5.0,
 * internal/SwitchBase.js: the input is its own slot, inputRef is gone).
 */
export function CheckboxField({ label, ref, ...props }: Props) {
  return <FormControlLabel label={label} control={<Checkbox {...props} slotProps={{ input: { ref } }} />} />
}
