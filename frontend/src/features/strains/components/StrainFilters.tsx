import { type ReactNode, useRef, useState } from 'react'
import { Box, Button, SelectField, Stack, TextField } from '@/components/ui'
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
const STATUS = [ALL, ...options(STATUS_LABELS, STATUSES)]
const statusOf = (value: string) => STATUSES.find((status) => status === value)
const kindOf = (value: string) => RESTRICTION_KINDS.find((kind) => kind === value)

/**
 * The list's filters, all in the URL: a selection applies at once, the text when submitted
 * (Enter or Search). The taxon filter takes the taxon, everything below it and the synonyms.
 */
export function StrainFilters({ filters, onChange, renderDepositor }: Props) {
  const [text, setText] = useState(filters.search ?? '')
  // The URL changed (back, forward, Clear filters): the text follows it. Adjusted while
  // rendering, not by remounting the form, which would drop the focus of the control in use.
  const [shown, setShown] = useState(filters.search)
  if (shown !== filters.search) {
    setShown(filters.search)
    setText(filters.search ?? '')
  }
  const [source, setSource] = useState(filters.isolation_source ?? '')
  const [shownSource, setShownSource] = useState(filters.isolation_source)
  if (shownSource !== filters.isolation_source) {
    setShownSource(filters.isolation_source)
    setSource(filters.isolation_source ?? '')
  }
  const taxon = useTaxon(filters.taxon)
  const textField = useRef<HTMLInputElement>(null)
  const active = Object.values(filters).some((value) => value !== undefined && value !== '')
  return (
    <Box
      component="form"
      aria-label="Filter strains"
      onSubmit={(event) => {
        event.preventDefault()
        onChange((current) => ({ ...current, search: text.trim() || undefined, isolation_source: source.trim() || undefined }))
      }}
      sx={{ mb: 3 }}
    >
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} useFlexGap sx={{ alignItems: { md: 'flex-start' }, flexWrap: 'wrap' }}>
        <TextField ref={textField} label="Number or name" type="search" autoComplete="off" value={text} onChange={(event) => setText(event.target.value)} />
        <Box sx={{ minWidth: { md: 260 } }}>
          <TaxonField
            label="Taxon"
            hint="With everything below it"
            // The list is filtered by a taxon the field cannot show: an empty field would hide that.
            error={filters.taxon && taxon.isError ? 'Could not load the taxon this list is filtered by.' : undefined}
            value={filters.taxon && taxon.data ? taxon.data : null}
            onChange={(picked) => onChange((current) => ({ ...current, taxon: picked?.public_id }))}
          />
        </Box>
        <SelectField
          sx={{ minWidth: { md: 150 } }}
          label="Risk group"
          options={RISK}
          value={filters.risk_group === undefined ? '' : String(filters.risk_group)}
          onChange={(event) => onChange((current) => ({ ...current, risk_group: riskGroupOf(event.target.value) }))}
        />
        <SelectField
          sx={{ minWidth: { md: 150 } }}
          label="Restriction"
          options={KINDS}
          value={filters.restriction ?? ''}
          onChange={(event) => onChange((current) => ({ ...current, restriction: kindOf(event.target.value) }))}
        />
        <SelectField
          sx={{ minWidth: { md: 150 } }}
          label="Status"
          options={STATUS}
          value={filters.status ?? ''}
          onChange={(event) => onChange((current) => ({ ...current, status: statusOf(event.target.value) }))}
        />
        <TextField label="Isolation source" hint="For example soil or river water" type="search" autoComplete="off" value={source} onChange={(event) => setSource(event.target.value)} />
        <SelectField
          sx={{ minWidth: { md: 180 } }}
          label="Country of origin"
          options={COUNTRIES}
          value={filters.country ?? ''}
          onChange={(event) => onChange((current) => ({ ...current, country: countryOf(event.target.value) }))}
        />
        {renderDepositor && <Box sx={{ minWidth: { md: 260 } }}>{renderDepositor(filters.depositor, (depositor) => onChange((current) => ({ ...current, depositor })))}</Box>}
        <Stack direction="row" spacing={1} sx={{ pt: 1 }}>
          <Button type="submit" variant="outlined">
            Search
          </Button>
          {active && (
            <Button
              onClick={() => {
                setText('')
                setSource('')
                onChange(() => ({}))
                // The button goes with the filters: focus moves to the first one.
                textField.current?.focus()
              }}
            >
              Clear filters
            </Button>
          )}
        </Stack>
      </Stack>
    </Box>
  )
}
