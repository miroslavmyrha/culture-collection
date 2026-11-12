import { type Ref, useEffect, useState } from 'react'
import { AutocompleteField } from '@/components/ui'
import { useDepositorList } from '../api/queries'
import { type Depositor, depositorLabel } from '../schemas'

type Props = {
  labId: string
  label?: string
  hint?: string
  error?: string | undefined
  value: Depositor | null
  onChange: (depositor: Depositor | null) => void
  onBlur?: () => void
  name?: string
  ref?: Ref<HTMLInputElement>
}

const WAIT_MS = 250

function useSettled(text: string): string {
  const [settled, setSettled] = useState(text)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(text), WAIT_MS)
    return () => clearTimeout(timer)
  }, [text])
  return settled
}

const textOf = (depositor: Depositor | null): string => (depositor ? depositorLabel(depositor) : '')

/** The text in the box: what was typed, reset to the chosen depositor's label whenever another one is chosen. */
function useBoxText(value: Depositor | null): [string, (text: string) => void] {
  const [text, setText] = useState(textOf(value))
  const [shown, setShown] = useState(value?.public_id)
  if (shown !== value?.public_id) {
    setShown(value?.public_id)
    setText(textOf(value))
  }
  return [text, setText]
}

/** The options to pick from: the search results while typing, else only the chosen depositor. Erased contacts cannot deposit. */
function useDepositorOptions(labId: string, value: Depositor | null, text: string) {
  const search = useSettled(text.trim())
  const typing = value === null || text !== depositorLabel(value)
  const found = useDepositorList(labId, { limit: 20, offset: 0, search }, typing && search.length > 0)
  const results = (found.data?.results ?? []).filter((d) => !d.erased)
  const chosen = value === null ? [] : [value]
  return { options: typing ? results : chosen, loading: found.isFetching, noOptionsText: search ? 'No depositor has this name' : 'Type a name' }
}

/** A depositor of the lab, found by name or institution. Erased contacts cannot deposit. */
export function DepositorField({ labId, label = 'Depositor', hint = 'Type part of the name or institution, then choose. Or add a new one.', error, value, onChange, onBlur, name, ref }: Props) {
  const [text, setText] = useBoxText(value)
  const found = useDepositorOptions(labId, value, text)
  return (
    <AutocompleteField<Depositor>
      label={label}
      hint={hint}
      error={error}
      name={name}
      ref={ref}
      onBlur={onBlur}
      options={found.options}
      value={value}
      onChange={onChange}
      inputValue={text}
      onInputChange={setText}
      getOptionLabel={depositorLabel}
      getOptionKey={(d) => d.public_id}
      isOptionEqualToValue={(a, b) => a.public_id === b.public_id}
      loading={found.loading}
      noOptionsText={found.noOptionsText}
    />
  )
}
