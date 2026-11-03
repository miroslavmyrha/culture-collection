import { zodResolver } from '@hookform/resolvers/zod'
import { type MouseEvent, useId, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Alert, Box, Button, ConfirmDialog, Link, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography } from '@/components/ui'
import { moment } from '@/lib/activity'
import { errorMessage, isApiError, readProblem } from '@/lib/api'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { applyServerErrors } from '@/lib/forms'
import { useEndVratAccess, useGrantVratAccess } from '../api/mutations'
import { useVratAccess } from '../api/queries'
import { endedBy, type LocationGrantInput, locationGrantSchema, personName, type VratAccess, type VratAccessInput, vratAccessSchema } from '../schemas'

type Open = { entry: VratAccess; open: boolean } | null

const regionSx = { border: 1, borderColor: 'divider', borderRadius: 1, bgcolor: 'background.paper', '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 2 } }

/**
 * For managers, on the lab page: the lab's list of the people with access to its highly risky
 * agents (VRAT), which act 281/2002 Sb., § 14a(4) asks the permit holder to keep up to date. Who
 * is on it now, with the End action, the form to put a member on it, the entries that ended, and
 * a link to the printable list. Separate from the regulated locations column: seeing where a
 * strain is stored is not access to the agent.
 */
export function VratAccessList({ labId }: { labId: string }) {
  const headingId = useId()
  return (
    <Box component="section" aria-labelledby={headingId} sx={{ mt: 5 }}>
      {/* tabIndex -1: a focus target when an ended entry takes the last End button with it. */}
      <Typography component="h2" variant="h6" id={headingId} tabIndex={-1} gutterBottom>
        VRAT access list
      </Typography>
      <Typography sx={{ mb: 2 }}>
        The people with access to the lab&apos;s highly risky agents (VRAT), which the permit holder keeps up to date (act 281/2002 Sb., § 14a(4)). Only
        members are on it: leaving the lab or a deactivated account ends an entry. Seeing regulated locations is a separate right.
      </Typography>
      <Entries labId={labId} />
      <AddToListForm labId={labId} />
    </Box>
  )
}

function Entries({ labId }: { labId: string }) {
  const list = useVratAccess(labId)
  const [open, setOpen] = useState<Open>(null)
  const spot = useRef<FocusReturn | null>(null)
  const show = (entry: VratAccess) => (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    setOpen({ entry, open: true })
  }
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }
  // The dialog renders in every state, outside the list's branches: ending the last open entry
  // must still run onExited to place the focus.
  return (
    <>
      <EntryTables labId={labId} list={list} show={show} />
      {open && <EndDialog labId={labId} entry={open.entry} open={open.open} onClose={() => setOpen((c) => c && { ...c, open: false })} onExited={exited} />}
    </>
  )
}

type TablesProps = { labId: string; list: ReturnType<typeof useVratAccess>; show: (entry: VratAccess) => (event: MouseEvent<HTMLButtonElement>) => void }

function EntryTables({ labId, list, show }: TablesProps) {
  if (list.data === undefined) {
    if (list.isPending) return <Typography>Loading the VRAT access list…</Typography>
    return <LoadError what="the VRAT access list" error={list.error} onRetry={() => void list.refetch()} />
  }
  const current = list.data.filter((e) => e.ended_at === null)
  const ended = list.data.filter((e) => e.ended_at !== null)
  return (
    <>
      <StaleNotice what="the VRAT access list" query={list} />
      {current.length === 0 ? (
        <Typography sx={{ mb: 2 }}>Nobody is on the VRAT access list.</Typography>
      ) : (
        <TableContainer sx={{ ...regionSx, mb: 2 }}>
          <Table aria-label="People with VRAT access">
            <TableHead>
              <TableRow>
                <TableCell>Username</TableCell>
                <TableCell>Name</TableCell>
                <TableCell>From</TableCell>
                <TableCell>Put on by</TableCell>
                <TableCell>Reason</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {current.map((e) => (
                <TableRow key={e.public_id}>
                  <TableCell sx={{ overflowWrap: 'anywhere' }}>{e.username}</TableCell>
                  <TableCell>{personName(e)}</TableCell>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>
                    <time dateTime={e.granted_at}>{moment(e.granted_at)}</time>
                  </TableCell>
                  <TableCell sx={{ overflowWrap: 'anywhere' }}>{e.granted_by}</TableCell>
                  <TableCell sx={{ overflowWrap: 'break-word' }}>{e.reason}</TableCell>
                  <TableCell>
                    <Button size="small" aria-label={`End VRAT access of ${e.username}`} onClick={show(e)}>
                      End access
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
      <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', mb: 3 }}>
        <Link to="/labs/$labId/vrat-access" params={{ labId }}>
          Print the VRAT access list
        </Link>
      </Stack>
      {ended.length > 0 && (
        <>
          <Typography component="h3" variant="subtitle1" gutterBottom>
            Ended entries
          </Typography>
          {/* No control inside and it may scroll sideways: a named region and a tab stop (WCAG 2.1.1). */}
          <TableContainer component="section" tabIndex={0} aria-label="Ended entries table" sx={{ ...regionSx, mb: 2 }}>
            <Table aria-label="Ended entries of the VRAT access list">
              <TableHead>
                <TableRow>
                  <TableCell>Username</TableCell>
                  <TableCell>From</TableCell>
                  <TableCell>Until</TableCell>
                  <TableCell>Ended by</TableCell>
                  <TableCell>Why it ended</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {ended.map((e) => (
                  <TableRow key={e.public_id}>
                    <TableCell sx={{ overflowWrap: 'anywhere' }}>{e.username}</TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>
                      <time dateTime={e.granted_at}>{moment(e.granted_at)}</time>
                    </TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{e.ended_at && <time dateTime={e.ended_at}>{moment(e.ended_at)}</time>}</TableCell>
                    <TableCell sx={{ overflowWrap: 'anywhere' }}>{endedBy(e)}</TableCell>
                    <TableCell sx={{ overflowWrap: 'break-word' }}>{e.end_reason}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </>
      )}
    </>
  )
}

/** The member by username, with a reason. Who cannot be on the list gets one message on the field. */
function AddToListForm({ labId }: { labId: string }) {
  const add = useGrantVratAccess(labId)
  const [failure, setFailure] = useState<string>()
  const [added, setAdded] = useState<string>()
  const { register, handleSubmit, formState, reset, setError } = useForm<VratAccessInput>({
    resolver: zodResolver(vratAccessSchema),
    defaultValues: { username: '', reason: '' },
  })
  const onSubmit = handleSubmit(({ username, reason }) => {
    if (add.isPending) return // aria-disabled keeps focus on the button, so guard here
    setFailure(undefined)
    setAdded(undefined)
    add.mutate(
      // The schema trims both fields.
      { username, reason },
      {
        onSuccess: (entry) => {
          reset()
          setAdded(entry.username)
        },
        onError: (error) => {
          // An unknown, inactive or foreign username: one message, whichever the server found.
          if (isApiError(error) && (error.code === 'invalid_user' || unknownUser(error.body))) {
            setError('username', { type: 'server', message: 'No active member of this lab has this username' }, { shouldFocus: true })
            return
          }
          if (isApiError(error) && error.code === 'already_on_list') {
            setError('username', { type: 'server', message: 'This member is on the list already' }, { shouldFocus: true })
            return
          }
          if (isApiError(error) && error.code === 'reason_required') {
            setError('reason', { type: 'server', message: 'Say why' }, { shouldFocus: true })
            return
          }
          if (!applyServerErrors(error, ['username', 'reason'], setError)) setFailure(errorMessage(error))
        },
      },
    )
  })
  const message = formState.errors.root?.server?.message ?? failure
  return (
    <Box component="form" onSubmit={onSubmit} noValidate aria-label="Put a member on the VRAT access list" sx={{ mt: 2 }}>
      <Typography component="h3" variant="subtitle1" gutterBottom>
        Put a member on the list
      </Typography>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ alignItems: 'flex-start' }}>
        <TextField label="Username" autoComplete="off" hint="An active member of this lab" error={formState.errors.username?.message} {...register('username')} />
        <TextField label="Reason" hint="Stored for good. Name no person." error={formState.errors.reason?.message} {...register('reason')} />
        <Button type="submit" variant="contained" aria-disabled={add.isPending} sx={{ mt: 1 }}>
          Put on the list
        </Button>
      </Stack>
      {message && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {message}
        </Alert>
      )}
      {added && <output>Put {added} on the VRAT access list.</output>}
    </Box>
  )
}

const unknownUser = (body: unknown) => readProblem(body)?.errors?.some((e) => e.attr === 'username' && e.code === 'does_not_exist') === true

type DialogProps = { labId: string; entry: VratAccess; open: boolean; onClose: () => void; onExited: () => void }

function EndDialog({ labId, entry, open, onClose, onExited }: DialogProps) {
  const end = useEndVratAccess(labId)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<LocationGrantInput>({
    resolver: zodResolver(locationGrantSchema),
    defaultValues: { reason: '' },
  })
  const onSubmit = handleSubmit(({ reason }) => {
    setFailure(undefined)
    end.mutate(
      { entryId: entry.public_id, reason },
      {
        onSuccess: onClose,
        onError: (error) => {
          if (isApiError(error) && error.code === 'reason_required') {
            setError('reason', { type: 'server', message: 'Say why' }, { shouldFocus: true })
            return
          }
          if (isApiError(error, 409) && error.code === 'vrat_access_ended') {
            setFailure('This entry has ended already. Reload to see it.')
            return
          }
          setFailure(applyServerErrors(error, ['reason'], setError) ? undefined : errorMessage(error))
        },
      },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      title={`End VRAT access of ${entry.username}`}
      description="From now on they are not on the lab's VRAT access list. The entry stays in the list's history with the reason."
      confirmLabel="End access"
      form={formId}
      pending={end.isPending}
      error={failure ?? formState.errors.root?.server?.message}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Reason" spacing={2} sx={{ mt: 2 }}>
        <TextField
          label="Reason"
          hint="Stored for good with the change. Name no person."
          multiline
          minRows={2}
          // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
          autoFocus
          error={formState.errors.reason?.message}
          {...register('reason')}
        />
      </Stack>
    </ConfirmDialog>
  )
}
