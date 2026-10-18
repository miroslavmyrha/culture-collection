import Autocomplete from '@mui/material/Autocomplete'
import type { ReactNode, Ref } from 'react'
import { TextField } from './TextField'

type Props<T> = {
  label: string
  /** Help that stays visible, also next to an error. */
  hint?: string | undefined
  /** The field's error message: marks the input invalid and becomes its description. */
  error?: string | undefined
  /** The options for what was typed: the caller searches, nothing is filtered here. */
  options: readonly T[]
  value: T | null
  onChange: (value: T | null) => void
  inputValue: string
  onInputChange: (text: string) => void
  getOptionLabel: (option: T) => string
  isOptionEqualToValue: (option: T, value: T) => boolean
  /** One option in the list; plain text by default. */
  renderOption?: (option: T) => ReactNode
  getOptionKey: (option: T) => string
  loading?: boolean
  noOptionsText?: string
  name?: string
  onBlur?: () => void
  /** A form dialog opens on its first field (WAI-ARIA dialog). */
  autoFocus?: boolean
  /** Lands on the <input>, so react-hook-form's Controller can focus it on an error. */
  ref?: Ref<HTMLInputElement>
}

/**
 * A combobox with a list of suggestions (WAI-ARIA combobox pattern, MUI Autocomplete): type
 * to search, ArrowDown and ArrowUp move through the list, Enter picks, Escape closes the
 * list and then clears. The input is our TextField, so its label, description and
 * aria-invalid are wired like every other field. The options come from the server for what
 * was typed, so MUI's own filtering is off (filterOptions passes them through).
 */
export function AutocompleteField<T>({
  label,
  hint,
  error,
  options,
  value,
  onChange,
  inputValue,
  onInputChange,
  getOptionLabel,
  isOptionEqualToValue,
  renderOption,
  getOptionKey,
  loading = false,
  noOptionsText = 'No matches',
  name,
  onBlur,
  autoFocus = false,
  ref,
}: Props<T>) {
  return (
    <Autocomplete<T>
      options={options}
      value={value}
      onChange={(_, picked) => onChange(picked)}
      inputValue={inputValue}
      onInputChange={(_, text) => onInputChange(text)}
      filterOptions={(all) => all}
      getOptionLabel={getOptionLabel}
      getOptionKey={getOptionKey}
      isOptionEqualToValue={isOptionEqualToValue}
      loading={loading}
      loadingText="Searching…"
      noOptionsText={noOptionsText}
      renderOption={({ key, ...props }, option) => (
        <li key={key} {...props}>
          {renderOption ? renderOption(option) : getOptionLabel(option)}
        </li>
      )}
      renderInput={(params) => (
        // oxlint-disable-next-line jsx-a11y/no-autofocus -- only form dialogs ask for it, on their first field
        <TextField {...params} label={label} name={name} hint={hint} error={error} onBlur={onBlur} autoFocus={autoFocus} ref={ref} />
      )}
    />
  )
}
