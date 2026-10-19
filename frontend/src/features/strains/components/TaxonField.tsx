import { type Ref, useEffect, useState } from 'react'
import { AutocompleteField } from '@/components/ui'
import { useTaxonSearch } from '../api/queries'
import { type Taxon, taxonLabel } from '../schemas'

type Props = {
  label: string
  hint?: string
  error?: string | undefined
  value: Taxon | null
  onChange: (taxon: Taxon | null) => void
  onBlur?: () => void
  name?: string
  autoFocus?: boolean
  ref?: Ref<HTMLInputElement>
}

const WAIT_MS = 250

/** The text a search runs for: what was typed, once typing has paused. */
function useSettled(text: string): string {
  const [settled, setSettled] = useState(text)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(text), WAIT_MS)
    return () => clearTimeout(timer)
  }, [text])
  return settled
}

/**
 * A taxon picked from the global taxonomy by name. Synonyms say which accepted name they stand
 * for, so a curator picking an old name knows what it means.
 */
export function TaxonField({ label, hint, error, value, onChange, onBlur, name, autoFocus, ref }: Props) {
  const [text, setText] = useState(value ? taxonLabel(value) : '')
  // A new value from outside (picked, loaded from the URL, cleared): the text shows it.
  const [shown, setShown] = useState(value?.public_id)
  if (shown !== value?.public_id) {
    setShown(value?.public_id)
    setText(value ? taxonLabel(value) : '')
  }
  const search = useSettled(text.trim())
  const typing = value === null || text !== taxonLabel(value)
  const taxa = useTaxonSearch(search, typing && search.length > 0)
  const results = taxa.data?.results ?? []
  return (
    <AutocompleteField<Taxon>
      label={label}
      hint={hint}
      error={error}
      name={name}
      ref={ref}
      onBlur={onBlur}
      // oxlint-disable-next-line jsx-a11y/no-autofocus -- passed on from a form dialog only
      autoFocus={autoFocus}
      options={typing ? results : value ? [value] : []}
      value={value}
      onChange={onChange}
      inputValue={text}
      onInputChange={setText}
      getOptionLabel={taxonLabel}
      getOptionKey={(taxon) => taxon.public_id}
      isOptionEqualToValue={(a, b) => a.public_id === b.public_id}
      renderOption={(taxon) => (
        <span>
          <i>{taxon.name}</i> {taxon.authority} <small>({taxon.status === 'synonym' ? `synonym, ${taxon.rank}` : taxon.rank})</small>
        </span>
      )}
      loading={taxa.isFetching}
      noOptionsText={search ? 'No taxon has this name' : 'Type a name'}
    />
  )
}
