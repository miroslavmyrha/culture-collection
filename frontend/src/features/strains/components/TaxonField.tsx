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

const textOf = (taxon: Taxon | null): string => (taxon ? taxonLabel(taxon) : '')

/**
 * The text of the field. A new value from outside (picked, loaded from the URL, cleared) is shown
 * in it: adjusted while rendering, not by an effect, which would draw one frame of the old text.
 */
function useTaxonText(value: Taxon | null): [string, (text: string) => void] {
  const [text, setText] = useState(textOf(value))
  const [shown, setShown] = useState(value?.public_id)
  if (shown !== value?.public_id) {
    setShown(value?.public_id)
    setText(textOf(value))
  }
  return [text, setText]
}

/** The options while typing are the search results, else only the chosen taxon. */
function optionsFor(typing: boolean, results: readonly Taxon[], value: Taxon | null): readonly Taxon[] {
  if (typing) return results
  return value ? [value] : []
}

function noOptionsText(failed: boolean, search: string): string {
  if (failed) return 'Could not search the taxa. Change the text to try again.'
  return search ? 'No taxon has this name' : 'Type a name'
}

function TaxonOption({ taxon }: { taxon: Taxon }) {
  return (
    <span>
      <i>{taxon.name}</i> {taxon.authority} <small>({taxon.status === 'synonym' ? `synonym, ${taxon.rank}` : taxon.rank})</small>
    </span>
  )
}

/**
 * A taxon picked from the global taxonomy by name. Synonyms say which accepted name they stand
 * for, so a curator picking an old name knows what it means.
 */
export function TaxonField({ label, hint, error, value, onChange, onBlur, name, autoFocus, ref }: Props) {
  const [text, setText] = useTaxonText(value)
  const search = useSettled(text.trim())
  const typing = value === null || text !== taxonLabel(value)
  const taxa = useTaxonSearch(search, typing && search.length > 0)
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
      options={optionsFor(typing, taxa.data?.results ?? [], value)}
      value={value}
      onChange={onChange}
      inputValue={text}
      onInputChange={setText}
      getOptionLabel={taxonLabel}
      getOptionKey={(taxon) => taxon.public_id}
      isOptionEqualToValue={(a, b) => a.public_id === b.public_id}
      renderOption={(taxon) => <TaxonOption taxon={taxon} />}
      loading={taxa.isFetching}
      noOptionsText={noOptionsText(taxa.isError, search)}
    />
  )
}
