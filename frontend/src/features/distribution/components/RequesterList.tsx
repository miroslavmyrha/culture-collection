import { type MouseEvent, useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { Pager, PastTheEnd } from '@/components/Pager'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Button, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography } from '@/components/ui'
import { countryName } from '@/lib/countries'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { safeHref } from '@/lib/safe'
import { useRequesterList } from '../api/queries'
import { LEGAL_FORM_LABELS, type Permit, PERMIT_KIND_LABELS, type Requester, type RequesterListParams, scientistName } from '../schemas'
import { EndPermitDialog, PermitDialog, RequesterDialog } from './RequesterDialogs'

type Props = {
  labId: string
  params: RequesterListParams
  /** Curators and managers add and change; the rest of the page reads. */
  canManage: boolean
  onOffsetChange: (offset: number) => void
  onSearch: (search: string | undefined) => void
}

type Open =
  | { kind: 'requester'; requester?: Requester; open: boolean }
  | { kind: 'permit'; requester: Requester; open: boolean }
  | { kind: 'end'; permit: Permit; open: boolean }
  | null

/** The lab's requesters: institutions with a confirmed microbiology laboratory, their
 * responsible scientist and the permits they hold, each with its file. */
export function RequesterList({ labId, params, canManage, onOffsetChange, onSearch }: Props) {
  const list = useRequesterList(labId, params)
  const [open, setOpen] = useState<Open>(null)
  const spot = useRef<FocusReturn | null>(null)
  const show = (next: NonNullable<Open>) => (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    setOpen(next)
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }
  return (
    <>
      <Search value={params.search} onSearch={onSearch} />
      {canManage && (
        <Box sx={{ mb: 2 }}>
          <Button variant="outlined" onClick={show({ kind: 'requester', open: true })}>
            Add a requester
          </Button>
        </Box>
      )}
      <Rows list={list} labId={labId} params={params} canManage={canManage} onOffsetChange={onOffsetChange} show={show} />
      {/* Outside the list's states, mounted until faded out, so onExited can place the focus. */}
      {open?.kind === 'requester' && <RequesterDialog labId={labId} requester={open.requester} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'permit' && <PermitDialog labId={labId} requester={open.requester} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'end' && <EndPermitDialog labId={labId} permit={open.permit} open={open.open} onClose={close} onExited={exited} />}
    </>
  )
}

type RowsProps = {
  list: ReturnType<typeof useRequesterList>
  labId: string
  params: RequesterListParams
  canManage: boolean
  onOffsetChange: (offset: number) => void
  show: (next: NonNullable<Open>) => (event: MouseEvent<HTMLButtonElement>) => void
}

function Rows({ list, labId, params, canManage, onOffsetChange, show }: RowsProps) {
  if (list.data === undefined) {
    if (list.isPending) return <Typography>Loading the requesters…</Typography>
    return <LoadError what="the requesters" error={list.error} onRetry={() => void list.refetch()} />
  }
  const stale = <StaleNotice what="the requesters" query={list} />
  const { count, results } = list.data
  if (count === 0) return <>{stale}<Typography>{params.search ? 'No requester matches this search.' : 'The lab has no requesters yet.'}</Typography></>
  if (results.length === 0) return <>{stale}<PastTheEnd onFirstPage={() => onOffsetChange(0)} /></>
  return (
    <section aria-label="Requesters" aria-busy={list.isPlaceholderData}>
      {stale}
      <Stack spacing={3}>
        {results.map((r) => (
          <Paper key={r.public_id} variant="outlined" component="article" aria-label={r.institution} sx={{ p: 2 }}>
            <Typography component="h2" variant="h6" sx={{ overflowWrap: 'anywhere' }}>
              {r.institution}
            </Typography>
            <Typography sx={{ overflowWrap: 'anywhere' }}>
              {LEGAL_FORM_LABELS[r.legal_form]}, {countryName(r.country)}
              {r.registration_number ? `, company number ${r.registration_number}` : ''}.
            </Typography>
            <Typography sx={{ overflowWrap: 'anywhere' }}>
              Responsible scientist: {scientistName(r)}
              {!r.erased && r.email ? `, ${r.email}` : ''}.
            </Typography>
            <Typography sx={{ overflowWrap: 'anywhere', whiteSpace: 'pre-line' }}>Delivery address: {r.erased ? 'erased' : r.postal_address}</Typography>
            <Typography sx={{ overflowWrap: 'anywhere' }}>
              Microbiology laboratory confirmed on {r.lab_confirmed_on}: {r.lab_evidence}
            </Typography>
            <Permits labId={labId} requester={r} canManage={canManage} show={show} />
            {canManage && !r.erased && (
              <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', mt: 2 }}>
                <Button variant="outlined" onClick={show({ kind: 'permit', requester: r, open: true })} aria-label={`Add a permit of ${r.institution}`}>
                  Add a permit
                </Button>
                <Button onClick={show({ kind: 'requester', requester: r, open: true })} aria-label={`Change ${r.institution}`}>
                  Change
                </Button>
              </Stack>
            )}
          </Paper>
        ))}
      </Stack>
      <Pager label="Requester pages" count={count} shown={results.length} limit={params.limit} offset={params.offset} loading={list.isPlaceholderData} onOffsetChange={onOffsetChange} />
    </section>
  )
}

function Permits({ labId, requester, canManage, show }: { labId: string; requester: Requester; canManage: boolean; show: RowsProps['show'] }) {
  if (requester.permits.length === 0) return <Typography sx={{ mt: 1 }}>No permit is recorded.</Typography>
  return (
    <TableContainer component={Paper} variant="outlined" sx={{ mt: 2 }}>
      <Table aria-label={`Permits of ${requester.institution}`} size="small">
        <TableHead>
          <TableRow>
            <TableCell>Permit</TableCell>
            <TableCell>Valid</TableCell>
            <TableCell>File</TableCell>
            {canManage && <TableCell>Action</TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {requester.permits.map((p) => (
            <TableRow key={p.public_id}>
              <TableCell sx={{ overflowWrap: 'anywhere' }}>
                {PERMIT_KIND_LABELS[p.kind]}: {p.reference} ({p.issuer})
                {p.covers ? `. Names: ${p.covers}` : ''}
                {p.quantity_allowed !== null ? `. ${p.quantity_allowed} allowed in ${p.sendings_allowed} sendings` : ''}
                {p.gmo_category !== null ? `. Category ${p.gmo_category}` : ''}
                {p.risk_group !== null ? `. Up to risk group ${p.risk_group}` : ''}
              </TableCell>
              <TableCell sx={{ whiteSpace: 'nowrap' }}>{validity(p)}</TableCell>
              <TableCell>
                <a href={safeHref(documentHref(labId, p.document.public_id))} download>
                  Download
                </a>
              </TableCell>
              {canManage && (
                <TableCell>
                  {p.ended_on === null && (
                    <Button onClick={show({ kind: 'end', permit: p, open: true })} aria-label={`End ${p.reference}`}>
                      End
                    </Button>
                  )}
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

const documentHref = (labId: string, documentId: string) => `/api/v1/labs/${encodeURIComponent(labId)}/documents/${encodeURIComponent(documentId)}/`

function validity(p: Permit): string {
  if (p.ended_on) return `Ended on ${p.ended_on}`
  const range = `From ${p.valid_from}${p.expires_on ? ` to ${p.expires_on}` : ''}`
  return p.valid_today ? range : `${range}, not valid today`
}

function Search({ value, onSearch }: { value: string | undefined; onSearch: (search: string | undefined) => void }) {
  const [text, setText] = useState(value ?? '')
  const [shown, setShown] = useState(value)
  if (shown !== value) {
    setShown(value)
    setText(value ?? '')
  }
  return (
    <Stack
      component="form"
      aria-label="Find requesters"
      direction="row"
      spacing={1}
      useFlexGap
      sx={{ flexWrap: 'wrap', alignItems: 'flex-start', mb: 2 }}
      onSubmit={(event) => {
        event.preventDefault()
        onSearch(text.trim() || undefined)
      }}
    >
      <TextField label="Institution or scientist" type="search" autoComplete="off" value={text} onChange={(event) => setText(event.target.value)} />
      <Button type="submit" variant="outlined" sx={{ mt: 1 }}>
        Search
      </Button>
    </Stack>
  )
}
