import { type MouseEvent, useId, useRef, useState } from 'react'
import { Button, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { useMemberList } from '../api/queries'
import { type Member, type PageParams, ROLE_LABELS, type Role } from '../schemas'
import { ChangeRoleDialog } from './ChangeRoleDialog'
import { LoadError } from './LoadError'
import { Pager, PastTheEnd } from './Pager'
import { RemoveMemberDialog } from './RemoveMemberDialog'

type Props = {
  labId: string
  labName: string
  /** Empty for members who may not manage: then the table has no manage controls. */
  grantable: Role[]
  params: PageParams
  onOffsetChange: (offset: number) => void
}

type Open = { kind: 'role' | 'remove'; member: Member; open: boolean } | null

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
  const show = (kind: 'role' | 'remove', member: Member) => (event: MouseEvent<HTMLButtonElement>) => {
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
      <MemberRows list={list} manage={manage} params={params} onOffsetChange={onOffsetChange} show={show} />
      {open?.kind === 'role' && (
        <ChangeRoleDialog labId={labId} member={open.member} roles={grantable} open={open.open} onClose={close} onExited={exited} />
      )}
      {open?.kind === 'remove' && (
        <RemoveMemberDialog labId={labId} labName={labName} member={open.member} open={open.open} onClose={close} onExited={exited} />
      )}
    </>
  )
}

type RowsProps = {
  list: ReturnType<typeof useMemberList>
  manage: boolean
  params: PageParams
  onOffsetChange: (offset: number) => void
  show: (kind: 'role' | 'remove', member: Member) => (event: MouseEvent<HTMLButtonElement>) => void
}

function MemberRows({ list, manage, params, onOffsetChange, show }: RowsProps) {
  if (list.isPending) return <Typography>Loading members…</Typography>
  if (list.isError) return <LoadError what="the members" error={list.error} onRetry={() => void list.refetch()} />
  const { count, results } = list.data
  if (count === 0) return <Typography>This lab has no members yet.</Typography>
  if (results.length === 0) return <PastTheEnd onFirstPage={() => onOffsetChange(0)} />
  return (
    <div aria-busy={list.isPlaceholderData}>
      <TableContainer component={Paper} variant="outlined">
        <Table aria-label="Members">
          <TableHead>
            <TableRow>
              <TableCell>Username</TableCell>
              <TableCell>Name</TableCell>
              <TableCell>Role</TableCell>
              {manage && <TableCell>Actions</TableCell>}
            </TableRow>
          </TableHead>
          <TableBody>
            {results.map((member) => (
              <TableRow key={member.public_id}>
                <TableCell>{member.username}</TableCell>
                <TableCell>{fullName(member)}</TableCell>
                <TableCell>{ROLE_LABELS[member.role]}</TableCell>
                {manage && (
                  <TableCell>
                    <Stack direction="row" spacing={1}>
                      <Button size="small" aria-label={`Change role of ${member.username}`} onClick={show('role', member)}>
                        Change role
                      </Button>
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
