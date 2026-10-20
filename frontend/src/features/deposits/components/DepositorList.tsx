import { type MouseEvent, useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Pager, PastTheEnd } from '@/components/Pager'
import { Box, Button, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography } from '@/components/ui'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { useDepositorList } from '../api/queries'
import { type Depositor, depositorName, type DepositorListParams } from '../schemas'
import { DepositorDialog } from './DepositorDialog'

type Props = {
  labId: string
  params: DepositorListParams
  /** The page owns the URL: it turns these into a navigation. */
  onOffsetChange: (offset: number) => void
  onSearch: (search: string | undefined) => void
}

type Open = { depositor?: Depositor; open: boolean } | null

/** The lab's depositors with their contacts, found by name or institution, added and changed in a dialog. */
export function DepositorList({ labId, params, onOffsetChange, onSearch }: Props) {
  const list = useDepositorList(labId, params)
  const [open, setOpen] = useState<Open>(null)
  const spot = useRef<FocusReturn | null>(null)
  const show = (depositor?: Depositor) => (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    setOpen({ depositor, open: true })
  }
  return (
    <>
      <Search value={params.search} onSearch={onSearch} />
      <Box sx={{ mb: 2 }}>
        <Button variant="outlined" onClick={show()}>
          Add a depositor
        </Button>
      </Box>
      <Rows list={list} params={params} onOffsetChange={onOffsetChange} onEdit={show} />
      {/* Outside the list's states, mounted until faded out, so onExited can place the focus. */}
      {open && (
        <DepositorDialog
          labId={labId}
          depositor={open.depositor}
          open={open.open}
          onClose={() => setOpen((current) => current && { ...current, open: false })}
          onExited={() => {
            spot.current?.restore()
            spot.current = null
            setOpen(null)
          }}
        />
      )}
    </>
  )
}

function Rows({
  list,
  params,
  onOffsetChange,
  onEdit,
}: {
  list: ReturnType<typeof useDepositorList>
  params: DepositorListParams
  onOffsetChange: (offset: number) => void
  onEdit: (depositor: Depositor) => (event: MouseEvent<HTMLButtonElement>) => void
}) {
  if (list.data === undefined) {
    if (list.isPending) return <Typography>Loading the depositors…</Typography>
    return <LoadError what="the depositors" error={list.error} onRetry={() => void list.refetch()} />
  }
  const stale = <StaleNotice what="the depositors" query={list} />
  const { count, results } = list.data
  if (count === 0) return <>{stale}<Typography>{params.search ? 'No depositor matches this search.' : 'The lab has no depositors yet.'}</Typography></>
  if (results.length === 0) return <>{stale}<PastTheEnd onFirstPage={() => onOffsetChange(0)} /></>
  return (
    <section aria-label="Depositors" aria-busy={list.isPlaceholderData}>
      {stale}
      <TableContainer component={Paper} variant="outlined">
        <Table aria-label="Depositors">
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>Institution</TableCell>
              <TableCell>E-mail</TableCell>
              <TableCell>Action</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {results.map((d) => (
              <TableRow key={d.public_id}>
                <TableCell sx={{ overflowWrap: 'break-word' }}>{depositorName(d)}</TableCell>
                <TableCell sx={{ overflowWrap: 'break-word' }}>{d.institution}</TableCell>
                <TableCell sx={{ overflowWrap: 'break-word' }}>{d.email}</TableCell>
                <TableCell>
                  {!d.erased && (
                    <Button onClick={onEdit(d)} aria-label={`Change ${d.name}`}>
                      Change
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <Pager label="Depositor pages" count={count} shown={results.length} limit={params.limit} offset={params.offset} loading={list.isPlaceholderData} onOffsetChange={onOffsetChange} />
    </section>
  )
}

/** The text applies when submitted. A new URL value (back, forward) replaces the text while
 * rendering, never by remounting the form, which would drop the focus of the control in use. */
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
      aria-label="Find depositors"
      direction="row"
      spacing={1}
      useFlexGap
      sx={{ flexWrap: 'wrap', alignItems: 'flex-start', mb: 2 }}
      onSubmit={(event) => {
        event.preventDefault()
        onSearch(text.trim() || undefined)
      }}
    >
      <TextField label="Name or institution" type="search" autoComplete="off" value={text} onChange={(event) => setText(event.target.value)} />
      <Button type="submit" variant="outlined" sx={{ mt: 1 }}>
        Search
      </Button>
    </Stack>
  )
}
