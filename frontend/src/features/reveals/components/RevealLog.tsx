import { useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { Pager, PastTheEnd } from '@/components/Pager'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Button, Link, Mono, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography } from '@/components/ui'
import { moment } from '@/lib/activity'
import { useFocusReturnOnUnmount } from '@/lib/focus'
import { useRevealList } from '../api/queries'
import { isDay, monthOf, personName, type Reveal, type RevealFilters as Filters, type RevealListParams } from '../schemas'

type Props = {
  labId: string
  params: RevealListParams
  /** The page owns the URL: it turns these into a navigation. */
  onOffsetChange: (offset: number) => void
  onPerson: (person: string | undefined) => void
  onClearFilters: () => void
}

/**
 * Who revealed where the lab's regulated vials are, newest first, a page at a time (#83). A row
 * names the person, the vial and when. It never shows the place: the server holds none for a
 * reveal, and this component renders only the fields it names below.
 */
export function RevealLog({ labId, params, onOffsetChange, onPerson, onClearFilters }: Props) {
  const list = useRevealList(labId, params)
  if (list.data === undefined) {
    if (list.isPending) return <Typography>Loading the reveals…</Typography>
    return <LoadError what="the reveals" error={list.error} onRetry={() => void list.refetch()} />
  }
  const stale = <StaleNotice what="the reveals" query={list} />
  const { count, results } = list.data
  if (count === 0 || results.length === 0) {
    return (
      <>
        {stale}
        <NoReveals count={count} filtered={isFiltered(params)} onClearFilters={onClearFilters} onFirstPage={() => onOffsetChange(0)} />
      </>
    )
  }
  const onePerson = params.person !== undefined
  return (
    <section aria-label="Reveals" aria-busy={list.isPlaceholderData}>
      {stale}
      {onePerson && <OnePerson name={personName(results[0]?.person ?? null)} onEveryone={() => onPerson(undefined)} />}
      <RevealTable labId={labId} results={results} onPerson={onePerson ? undefined : onPerson} />
      <Pager label="Reveal pages" count={count} shown={results.length} limit={params.limit} offset={params.offset} loading={list.isPlaceholderData} onOffsetChange={onOffsetChange} />
    </section>
  )
}

const isFiltered = (params: Filters | RevealListParams) => params.since !== undefined || params.until !== undefined || params.person !== undefined

type NoRevealsProps = { count: number; filtered: boolean; onClearFilters: () => void; onFirstPage: () => void }

/** Why the table is empty: the filters match nothing, the lab has no reveal, or the page is past the end. */
function NoReveals({ count, filtered, onClearFilters, onFirstPage }: NoRevealsProps) {
  if (count > 0) return <PastTheEnd onFirstPage={onFirstPage} />
  if (filtered) return <NoMatch onClearFilters={onClearFilters} />
  return <Typography>Nobody has revealed where a regulated vial of this lab is stored.</Typography>
}

/** The reveals of the page, one row each. */
function RevealTable({ labId, results, onPerson }: { labId: string; results: readonly Reveal[]; onPerson: ((person: string) => void) | undefined }) {
  return (
    <TableContainer component={Paper} variant="outlined">
      <Table aria-label="Reveals">
        <TableHead>
          <TableRow>
            <TableCell>When</TableCell>
            <TableCell>Who</TableCell>
            <TableCell>Vial</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {/* A reveal has no id of its own: one person reveals one vial once per transaction, so
              the moment, the vial and the person tell rows apart. */}
          {results.map((reveal) => (
            <RevealRow key={`${reveal.occurred_at} ${reveal.vial} ${reveal.person?.public_id ?? ''}`} labId={labId} reveal={reveal} onPerson={onPerson} />
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

function RevealRow({ labId, reveal, onPerson }: { labId: string; reveal: Reveal; onPerson: ((person: string) => void) | undefined }) {
  const who = personName(reveal.person)
  const person = reveal.person
  return (
    <TableRow>
      <TableCell sx={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
        <time dateTime={reveal.occurred_at}>{moment(reveal.occurred_at)}</time>
      </TableCell>
      <TableCell sx={{ overflowWrap: 'anywhere' }}>
        {who}
        {/* Not for an erased person: every erased person reads the same, so the button would not say whose. */}
        {onPerson !== undefined && person !== null && !person.erased && (
          <Button size="small" sx={{ ml: 1 }} aria-label={`Only the reveals of ${who}`} onClick={() => onPerson(person.public_id)}>
            Only these
          </Button>
        )}
      </TableCell>
      <TableCell sx={{ overflowWrap: 'anywhere' }}>
        <RevealedVial labId={labId} reveal={reveal} />
      </TableCell>
    </TableRow>
  )
}

/** The vial as a link to its strain, or the words that it is gone. */
function RevealedVial({ labId, reveal }: { labId: string; reveal: Reveal }) {
  if (reveal.vial_label === null || reveal.strain === null) return <>A vial no longer in the lab</>
  return (
    <Link to="/labs/$labId/strains/$strainId/material" params={{ labId, strainId: reveal.strain }} search={{ vial: reveal.vial }}>
      <Mono>{reveal.vial_label}</Mono>
    </Link>
  )
}

function OnePerson({ name, onEveryone }: { name: string; onEveryone: () => void }) {
  const remember = useFocusReturnOnUnmount()
  return (
    <Typography sx={{ mb: 2 }}>
      The reveals of {name}.{' '}
      <Button
        onClick={(event) => {
          remember(event.currentTarget)
          onEveryone()
        }}
      >
        Show everyone
      </Button>
    </Typography>
  )
}

function NoMatch({ onClearFilters }: { onClearFilters: () => void }) {
  const remember = useFocusReturnOnUnmount()
  return (
    <Typography>
      No reveal matches these filters.{' '}
      <Button
        onClick={(event) => {
          remember(event.currentTarget)
          onClearFilters()
        }}
      >
        Clear filters
      </Button>
    </Typography>
  )
}

const NOT_A_DAY = 'Enter a day as YYYY-MM-DD.'

/** The message for the "to" day: not a day, or before the first. */
function untilError(from: string, to: string): string | undefined {
  if (to === '') return undefined
  if (!isDay(to)) return NOT_A_DAY
  return from !== '' && to < from ? 'The last day comes before the first.' : undefined
}

/** What is wrong with the two days as typed (already trimmed), if anything. */
const dayErrors = (from: string, to: string) => ({ since: from !== '' && !isDay(from) ? NOT_A_DAY : undefined, until: untilError(from, to) })

/** The button that drops every filter, shown only while one is set. */
function ClearFilters({ active, onClear }: { active: boolean; onClear: () => void }) {
  if (!active) return null
  return <Button onClick={onClear}>Clear filters</Button>
}

/**
 * The days, from and to, both included and Czech days on the server. Applied when submitted;
 * "This month" fills and applies the current month at once. Both live in the URL.
 */
export function RevealFilters({ filters, onChange }: { filters: Filters; onChange: (update: (current: Filters) => Filters) => void }) {
  const [since, setSince] = useState(filters.since ?? '')
  const [until, setUntil] = useState(filters.until ?? '')
  const [errors, setErrors] = useState<{ since?: string; until?: string }>({})
  // The URL changed (back, forward, Clear filters): the fields follow it while rendering.
  const [shown, setShown] = useState({ since: filters.since, until: filters.until })
  if (shown.since !== filters.since || shown.until !== filters.until) {
    setShown({ since: filters.since, until: filters.until })
    setSince(filters.since ?? '')
    setUntil(filters.until ?? '')
    setErrors({})
  }
  const sinceField = useRef<HTMLInputElement>(null)
  const untilField = useRef<HTMLInputElement>(null)
  const apply = (from: string, to: string) => onChange((current) => ({ ...current, since: from || undefined, until: to || undefined }))
  return (
    <Box
      component="form"
      aria-label="Filter reveals"
      noValidate
      onSubmit={(event) => {
        event.preventDefault()
        const from = since.trim()
        const to = until.trim()
        const found = dayErrors(from, to)
        setErrors(found)
        if (found.since !== undefined) return sinceField.current?.focus()
        if (found.until !== undefined) return untilField.current?.focus()
        apply(from, to)
      }}
      sx={{ mb: 3 }}
    >
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} useFlexGap sx={{ alignItems: { md: 'flex-start' }, flexWrap: 'wrap' }}>
        <TextField ref={sinceField} label="From" hint="YYYY-MM-DD" autoComplete="off" error={errors.since} value={since} onChange={(event) => setSince(event.target.value)} />
        <TextField ref={untilField} label="To" hint="YYYY-MM-DD" autoComplete="off" error={errors.until} value={until} onChange={(event) => setUntil(event.target.value)} />
        <Stack direction="row" spacing={1} useFlexGap sx={{ pt: 1, flexWrap: 'wrap' }}>
          <Button type="submit" variant="outlined">
            Show
          </Button>
          <Button
            onClick={() => {
              const month = monthOf(new Date())
              setErrors({})
              apply(month.since, month.until)
            }}
          >
            This month
          </Button>
          <ClearFilters
            active={isFiltered(filters)}
            onClear={() => {
              setErrors({})
              onChange(() => ({}))
              sinceField.current?.focus()
            }}
          />
        </Stack>
      </Stack>
    </Box>
  )
}
