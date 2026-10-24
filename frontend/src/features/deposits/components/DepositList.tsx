import { useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Pager, PastTheEnd } from '@/components/Pager'
import { Box, Button, Link, Mono, Paper, SelectField, Stack, StatusChip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography } from '@/components/ui'
import { DEPOSIT_TONES } from '@/lib/tones'
import { useFocusReturnOnUnmount } from '@/lib/focus'
import { useDepositList } from '../api/queries'
import { type DepositFilters as Filters, type DepositListParams, depositorLabel, options, STATUS_LABELS, STATUSES } from '../schemas'

type Props = {
  labId: string
  params: DepositListParams
  /** The page owns the URL: it turns these into a navigation. */
  onOffsetChange: (offset: number) => void
  onClearFilters: () => void
}

/** The lab's deposits, newest receipt first, filtered by the URL, a page at a time. */
export function DepositList({ labId, params, onOffsetChange, onClearFilters }: Props) {
  const list = useDepositList(labId, params)
  if (list.data === undefined) {
    if (list.isPending) return <Typography>Loading the deposits…</Typography>
    return <LoadError what="the deposits" error={list.error} onRetry={() => void list.refetch()} />
  }
  const stale = <StaleNotice what="the deposits" query={list} />
  const { count, results } = list.data
  const filtered = params.status !== undefined || Boolean(params.search)
  if (count === 0 && filtered) return <>{stale}<NoMatch onClearFilters={onClearFilters} /></>
  if (count === 0) return <>{stale}<Typography>The lab has received no deposits yet.</Typography></>
  if (results.length === 0) return <>{stale}<PastTheEnd onFirstPage={() => onOffsetChange(0)} /></>
  return (
    <section aria-label="Deposits" aria-busy={list.isPlaceholderData}>
      {stale}
      <TableContainer component={Paper} variant="outlined">
        <Table aria-label="Deposits">
          <TableHead>
            <TableRow>
              <TableCell>Received</TableCell>
              <TableCell>Name as received</TableCell>
              <TableCell>Depositor</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Strain</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {results.map((d) => (
              <TableRow key={d.public_id}>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>{d.received_on}</TableCell>
                <TableCell sx={{ overflowWrap: 'anywhere' }}>
                  <Link to="/labs/$labId/deposits/$depositId" params={{ labId, depositId: d.public_id }}>
                    {d.name_as_received}
                  </Link>
                </TableCell>
                <TableCell sx={{ overflowWrap: 'anywhere' }}>{depositorLabel(d.depositor)}</TableCell>
                <TableCell>
                  <StatusChip tone={DEPOSIT_TONES[d.status]}>{STATUS_LABELS[d.status]}</StatusChip>
                </TableCell>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>
                  {d.strain ? (
                    <Link to="/labs/$labId/strains/$strainId" params={{ labId, strainId: d.strain.public_id }}>
                      <Mono>{d.strain.accession_number ?? 'pending'}</Mono>
                    </Link>
                  ) : (
                    'None'
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <Pager label="Deposit pages" count={count} shown={results.length} limit={params.limit} offset={params.offset} loading={list.isPlaceholderData} onOffsetChange={onOffsetChange} />
    </section>
  )
}

function NoMatch({ onClearFilters }: { onClearFilters: () => void }) {
  const remember = useFocusReturnOnUnmount()
  return (
    <Typography>
      No deposit matches these filters.{' '}
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
export function DepositFilters({ filters, onChange }: { filters: Filters; onChange: (update: (current: Filters) => Filters) => void }) {
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
      aria-label="Filter deposits"
      onSubmit={(event) => {
        event.preventDefault()
        onChange((current) => ({ ...current, search: text.trim() || undefined }))
      }}
      sx={{ mb: 3 }}
    >
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} useFlexGap sx={{ alignItems: { md: 'flex-start' }, flexWrap: 'wrap' }}>
        <TextField ref={textField} label="Name, depositor or number" type="search" autoComplete="off" value={text} onChange={(event) => setText(event.target.value)} />
        <SelectField
          sx={{ minWidth: { md: 160 } }}
          label="Status"
          options={STATUS_OPTIONS}
          value={filters.status ?? ''}
          onChange={(event) => onChange((current) => ({ ...current, status: statusOf(event.target.value) }))}
        />
        <Stack direction="row" spacing={1} sx={{ pt: 1 }}>
          <Button type="submit" variant="outlined">
            Search
          </Button>
          {active && (
            <Button
              onClick={() => {
                setText('')
                onChange(() => ({}))
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
