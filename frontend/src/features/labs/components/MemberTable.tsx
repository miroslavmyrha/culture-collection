import { type MouseEvent, useId, useRef, useState } from 'react'
import { Button, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { useLocationGrants, useMemberList } from '../api/queries'
import { type LocationGrant, type Member, type PageParams, ROLE_LABELS, type Role } from '../schemas'
import { ChangeRoleDialog } from './ChangeRoleDialog'
import { LocationGrantDialog } from './LocationGrantDialog'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Pager, PastTheEnd } from '@/components/Pager'
import { RemoveMemberDialog } from './RemoveMemberDialog'

type Props = {
  labId: string
  labName: string
  /** Empty for members who may not manage: then the table has no manage controls. */
  grantable: Role[]
  params: PageParams
  onOffsetChange: (offset: number) => void
}

type Kind = 'role' | 'remove' | 'location'
type Open = { kind: Kind; member: Member; open: boolean } | null

const fullName = (m: Member) => [m.first_name, m.last_name].filter(Boolean).join(' ')

/** The members of a lab under their heading. The heading is where focus goes when a removal leaves no row to go to. */
export function MemberTable(props: Props) {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId}>
      {/* tabIndex -1: a focus target after a removal, not a stop in the tab order. */}
      <Typography component="h2" variant="h6" id={headingId} tabIndex={-1} gutterBottom>
        Members
      </Typography>
      <Members {...props} />
    </section>
  )
}

function Members({ labId, labName, grantable, params, onOffsetChange }: Props) {
  const list = useMemberList(labId, params)
  const [open, setOpen] = useState<Open>(null)
  // The trigger, taken when a dialog opens: a removal takes its row, and with it the button.
  const spot = useRef<FocusReturn | null>(null)
  const manage = grantable.length > 0
  // Who may see regulated locations (ADR 0009): managers only, so nobody else asks.
  const grants = useLocationGrants(labId, manage)
  const grantOf = (member: Member) => grants.data?.find((g) => g.member === member.public_id)
  const show = (kind: Kind, member: Member) => (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    setOpen({ kind, member, open: true })
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }
  // The dialogs render in every state: removing the last row of a page shows "This page is
  // empty", and a dialog unmounted there would never run onExited to place the focus.
  return (
    <>
      <MemberRows
        list={list}
        manage={manage}
        grants={manage ? { loaded: grants.data !== undefined, failed: grants.data === undefined && grants.isError, of: grantOf } : undefined}
        params={params}
        onOffsetChange={onOffsetChange}
        show={show}
      />
      {open?.kind === 'role' && (
        <ChangeRoleDialog labId={labId} member={open.member} roles={grantable} open={open.open} onClose={close} onExited={exited} />
      )}
      {open?.kind === 'location' && (
        <LocationGrantDialog labId={labId} member={open.member} grant={grantOf(open.member)} open={open.open} onClose={close} onExited={exited} />
      )}
      {open?.kind === 'remove' && (
        <RemoveMemberDialog labId={labId} labName={labName} member={open.member} open={open.open} onClose={close} onExited={exited} />
      )}
    </>
  )
}

type Grants = { loaded: boolean; failed: boolean; of: (member: Member) => LocationGrant | undefined }

type RowsProps = {
  list: ReturnType<typeof useMemberList>
  manage: boolean
  grants: Grants | undefined
  params: PageParams
  onOffsetChange: (offset: number) => void
  show: (kind: Kind, member: Member) => (event: MouseEvent<HTMLButtonElement>) => void
}

function MemberRows({ list, manage, grants, params, onOffsetChange, show }: RowsProps) {
  if (list.data === undefined) {
    if (list.isPending) return <Typography>Loading members…</Typography>
    return <LoadError what="the members" error={list.error} onRetry={() => void list.refetch()} />
  }
  const stale = <StaleNotice what="the members" query={list} />
  const { count, results } = list.data
  if (count === 0) return <>{stale}<Typography>This lab has no members yet.</Typography></>
  if (results.length === 0) return <>{stale}<PastTheEnd onFirstPage={() => onOffsetChange(0)} /></>
  return (
    <div aria-busy={list.isPlaceholderData}>
      {stale}
      <TableContainer component={Paper} variant="outlined">
        <Table aria-label="Members">
          <TableHead>
            <TableRow>
              <TableCell>Username</TableCell>
              <TableCell>Name</TableCell>
              <TableCell>Role</TableCell>
              {grants && <TableCell>Regulated locations</TableCell>}
              {manage && <TableCell>Actions</TableCell>}
            </TableRow>
          </TableHead>
          <TableBody>
            {results.map((member) => (
              <TableRow key={member.public_id}>
                <TableCell>{member.username}</TableCell>
                <TableCell>{fullName(member)}</TableCell>
                <TableCell>{ROLE_LABELS[member.role]}</TableCell>
                {grants && <TableCell>{locationCell(grants, member)}</TableCell>}
                {manage && (
                  <TableCell>
                    <Stack direction="row" spacing={1}>
                      <Button size="small" aria-label={`Change role of ${member.username}`} onClick={show('role', member)}>
                        Change role
                      </Button>
                      {grants?.loaded && (
                        <Button
                          size="small"
                          aria-label={`${grants.of(member) ? 'Revoke' : 'Grant'} regulated locations for ${member.username}`}
                          onClick={show('location', member)}
                        >
                          {grants.of(member) ? 'Revoke locations' : 'Grant locations'}
                        </Button>
                      )}
                      <Button size="small" color="error" aria-label={`Remove ${member.username}`} onClick={show('remove', member)}>
                        Remove
                      </Button>
                    </Stack>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <Pager label="Member pages" count={count} shown={results.length} {...params} loading={list.isPlaceholderData} onOffsetChange={onOffsetChange} />
    </div>
  )
}

function locationCell(grants: Grants, member: Member): string {
  if (grants.failed) return 'Could not load'
  if (!grants.loaded) return 'Loading…'
  return grants.of(member) ? 'May see' : 'Hidden'
}
