import { useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { Pager, PastTheEnd } from '@/components/Pager'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Button, Link, Paper, SelectField, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography } from '@/components/ui'
import { countryName } from '@/lib/countries'
import { useFocusReturnOnUnmount } from '@/lib/focus'
import { useRequestList } from '../api/queries'
import { options, type RequestFilters as Filters, type RequestListParams, STATUS_LABELS, STATUSES, USE_LABELS } from '../schemas'

type Props = {
  labId: string
  params: RequestListParams
  /** The page owns the URL: it turns these into a navigation. */
  onOffsetChange: (offset: number) => void
  onClearFilters: () => void
}

/** The lab's requests, newest first, filtered by the URL, a page at a time. */
export function RequestList({ labId, params, onOffsetChange, onClearFilters }: Props) {
  const list = useRequestList(labId, params)
  if (list.data === undefined) {
    if (list.isPending) return <Typography>Loading the requests…</Typography>
    return <LoadError what="the requests" error={list.error} onRetry={() => void list.refetch()} />
  }
  const stale = <StaleNotice what="the requests" query={list} />
  const { count, results } = list.data
  const filtered = params.status !== undefined || Boolean(params.search)
  if (count === 0 && filtered) return <>{stale}<NoMatch onClearFilters={onClearFilters} /></>
  if (count === 0) return <>{stale}<Typography>No request has been entered yet.</Typography></>
  if (results.length === 0) return <>{stale}<PastTheEnd onFirstPage={() => onOffsetChange(0)} /></>
  return (
    <section aria-label="Requests" aria-busy={list.isPlaceholderData}>
      {stale}
      <TableContainer component={Paper} variant="outlined">
        <Table aria-label="Requests">
          <TableHead>
            <TableRow>
              <TableCell>Number</TableCell>
              <TableCell>Requester</TableCell>
              <TableCell>Use</TableCell>
              <TableCell>Strains and vials</TableCell>
              <TableCell>Status</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {results.map((r) => (
              <TableRow key={r.public_id}>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>
                  <Link to="/labs/$labId/requests/$requestId" params={{ labId, requestId: r.public_id }} aria-label={`Request ${r.number}`}>
                    {r.number}
                  </Link>
                </TableCell>
                <TableCell sx={{ overflowWrap: 'anywhere' }}>
                  {r.requester.institution}, {countryName(r.requester.country)}
                </TableCell>
                <TableCell>{USE_LABELS[r.use]}</TableCell>
                <TableCell>
                  {r.line_count === 1 ? '1 strain' : `${r.line_count} strains`}, {r.vial_count === 1 ? '1 vial' : `${r.vial_count} vials`}
                  {r.regulated ? ', regulated' : ''}
                </TableCell>
                <TableCell>{STATUS_LABELS[r.status]}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <Pager label="Request pages" count={count} shown={results.length} limit={params.limit} offset={params.offset} loading={list.isPlaceholderData} onOffsetChange={onOffsetChange} />
    </section>
  )
}

function NoMatch({ onClearFilters }: { onClearFilters: () => void }) {
  const remember = useFocusReturnOnUnmount()
  return (
    <Typography>
      No request matches these filters.{' '}
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

const STATUS_OPTIONS = [{ value: '', label: 'All' }, ...options(STATUS_LABELS, STATUSES)]
const statusOf = (value: string) => STATUSES.find((status) => status === value)

/** The status applies at once, the text when submitted. Both live in the URL. */
export function RequestFilters({ filters, onChange }: { filters: Filters; onChange: (filters: Filters) => void }) {
  const [text, setText] = useState(filters.search ?? '')
  // The URL changed (back, forward, Clear filters): the text follows it while rendering.
  const [shown, setShown] = useState(filters.search)
  if (shown !== filters.search) {
    setShown(filters.search)
    setText(filters.search ?? '')
  }
  const textField = useRef<HTMLInputElement>(null)
  const active = filters.status !== undefined || Boolean(filters.search)
  return (
    <Box
      component="form"
      aria-label="Filter requests"
      onSubmit={(event) => {
        event.preventDefault()
        onChange({ ...filters, search: text.trim() || undefined })
      }}
      sx={{ mb: 3 }}
    >
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} useFlexGap sx={{ alignItems: { md: 'flex-start' }, flexWrap: 'wrap' }}>
        <TextField ref={textField} label="Number, requester or strain" type="search" autoComplete="off" value={text} onChange={(event) => setText(event.target.value)} />
        <SelectField
          sx={{ minWidth: { md: 200 } }}
          label="Status"
          options={STATUS_OPTIONS}
          value={filters.status ?? ''}
          onChange={(event) => onChange({ ...filters, status: statusOf(event.target.value) })}
        />
        <Stack direction="row" spacing={1} sx={{ pt: 1 }}>
          <Button type="submit" variant="outlined">
            Search
          </Button>
          {active && (
            <Button
              onClick={() => {
                setText('')
                onChange({})
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
