import { type ReactNode, useRef, useState } from 'react'
import { Box, Button, CheckboxField, SelectField, Stack, TextField } from '@/components/ui'
import { COUNTRY_CODES, countryOptions } from '@/lib/countries'
import { useTaxon } from '../api/queries'
import {
  options,
  RESTRICTION_KINDS,
  RESTRICTION_LABELS,
  RISK_GROUPS,
  STATUS_LABELS,
  type StrainFilters as Filters,
  type StrainStatus,
} from '../schemas'
import { TaxonField } from './TaxonField'

type Props = {
  filters: Filters
  /** The page owns the URL: it turns new filters into a navigation (back to the first page). */
  onChange: (update: (current: Filters) => Filters) => void
  /**
   * The depositor filter, drawn by the deposits feature (a render prop, so strains do not import
   * it) and given only to those who may open deposits: a depositor is a person's contact.
   */
  renderDepositor?: (value: string | undefined, onPick: (depositor: string | undefined) => void) => ReactNode
}

const ALL = { value: '', label: 'All' }
const RISK = [ALL, ...RISK_GROUPS.map((group) => ({ value: String(group), label: String(group) }))]
const KINDS = [ALL, ...options(RESTRICTION_LABELS, RESTRICTION_KINDS)]

const COUNTRIES = [ALL, ...countryOptions().slice(1)] // without "Unknown": no code means no filter
const countryOf = (value: string) => COUNTRY_CODES.find((code) => code === value)

const riskGroupOf = (value: string) => RISK_GROUPS.find((group) => String(group) === value)
const STATUSES: StrainStatus[] = ['pending', 'active', 'restricted', 'deaccessioned']
// Without a status the list shows the strains in the collection: a deaccessioned one only when
// chosen (#20).
const STATUS = [{ value: '', label: 'In the collection' }, ...options(STATUS_LABELS, STATUSES)]
const statusOf = (value: string) => STATUSES.find((status) => status === value)
const kindOf = (value: string) => RESTRICTION_KINDS.find((kind) => kind === value)

type SetFilters = (patch: Partial<Filters>) => void

/**
 * A text kept beside the URL's value: typed freely, applied when submitted. The URL changed (back,
 * forward, Clear filters): the text follows it. Adjusted while rendering, not by remounting the
 * form, which would drop the focus of the control in use.
 */
function useUrlText(url: string | undefined): [string, (text: string) => void] {
  const [text, setText] = useState(url ?? '')
  const [shown, setShown] = useState(url)
  if (shown !== url) {
    setShown(url)
    setText(url ?? '')
  }
  return [text, setText]
}

/** The taxon filter takes the taxon, everything below it and the synonyms. */
function TaxonFilter({ taxonId, set }: { taxonId: string | undefined; set: SetFilters }) {
  const taxon = useTaxon(taxonId)
  return (
    <Box sx={{ minWidth: { md: 260 } }}>
      <TaxonField
        label="Taxon"
        hint="With everything below it"
        // The list is filtered by a taxon the field cannot show: an empty field would hide that.
        error={taxonId && taxon.isError ? 'Could not load the taxon this list is filtered by.' : undefined}
        value={taxonId && taxon.data ? taxon.data : null}
        onChange={(picked) => set({ taxon: picked?.public_id })}
      />
    </Box>
  )
}

/** Risk group, restriction and status: a choice applies at once. */
function ClassSelects({ filters, set }: { filters: Filters; set: SetFilters }) {
  return (
    <>
      <SelectField
        sx={{ minWidth: { md: 150 } }}
        label="Risk group"
        options={RISK}
        value={filters.risk_group === undefined ? '' : String(filters.risk_group)}
        onChange={(event) => set({ risk_group: riskGroupOf(event.target.value) })}
      />
      <SelectField
        sx={{ minWidth: { md: 150 } }}
        label="Restriction"
        options={KINDS}
        value={filters.restriction ?? ''}
        onChange={(event) => set({ restriction: kindOf(event.target.value) })}
      />
      <SelectField
        sx={{ minWidth: { md: 150 } }}
        label="Status"
        options={STATUS}
        value={filters.status ?? ''}
        onChange={(event) => set({ status: statusOf(event.target.value) })}
      />
    </>
  )
}

type ButtonsProps = { active: boolean; onClear: () => void }

function FilterButtons({ active, onClear }: ButtonsProps) {
  return (
    <Stack direction="row" spacing={1} sx={{ pt: 1 }}>
      <Button type="submit" variant="outlined">
        Search
      </Button>
      {active && <Button onClick={onClear}>Clear filters</Button>}
    </Stack>
  )
}

/**
 * The list's filters, all in the URL: a selection applies at once, the text when submitted
 * (Enter or Search). The taxon filter takes the taxon, everything below it and the synonyms.
 */
export function StrainFilters({ filters, onChange, renderDepositor }: Props) {
  const [text, setText] = useUrlText(filters.search)
  const [source, setSource] = useUrlText(filters.isolation_source)
  const textField = useRef<HTMLInputElement>(null)
  const active = Object.values(filters).some((value) => value !== undefined && value !== '')
  const set: SetFilters = (patch) => onChange((current) => ({ ...current, ...patch }))
  const clear = () => {
    setText('')
    setSource('')
    onChange(() => ({}))
    // The button goes with the filters: focus moves to the first one.
    textField.current?.focus()
  }
  return (
    <Box
      component="form"
      aria-label="Filter strains"
      onSubmit={(event) => {
        event.preventDefault()
        set({ search: text.trim() || undefined, isolation_source: source.trim() || undefined })
      }}
      sx={{ mb: 3 }}
    >
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} useFlexGap sx={{ alignItems: { md: 'flex-start' }, flexWrap: 'wrap' }}>
        <TextField ref={textField} label="Number or name" type="search" autoComplete="off" value={text} onChange={(event) => setText(event.target.value)} />
        <TaxonFilter taxonId={filters.taxon} set={set} />
        <ClassSelects filters={filters} set={set} />
        <TextField label="Isolation source" hint="For example soil or river water" type="search" autoComplete="off" value={source} onChange={(event) => setSource(event.target.value)} />
        <SelectField
          sx={{ minWidth: { md: 180 } }}
          label="Country of origin"
          options={COUNTRIES}
          value={filters.country ?? ''}
          onChange={(event) => set({ country: countryOf(event.target.value) })}
        />
        <CheckboxField
          label="Only with vials for distribution"
          checked={filters.distributable === true}
          onChange={(event) => set({ distributable: event.target.checked ? true : undefined })}
        />
        {renderDepositor && <Box sx={{ minWidth: { md: 260 } }}>{renderDepositor(filters.depositor, (depositor) => set({ depositor }))}</Box>}
        <FilterButtons active={active} onClear={clear} />
      </Stack>
    </Box>
  )
}
