import { useState } from 'react'
import { Button, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
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

type Open = { kind: 'role' | 'remove'; member: Member } | null

const fullName = (m: Member) => [m.first_name, m.last_name].filter(Boolean).join(' ')

export function MemberTable({ labId, labName, grantable, params, onOffsetChange }: Props) {
  const list = useMemberList(labId, params)
  const [open, setOpen] = useState<Open>(null)
  const manage = grantable.length > 0
  if (list.isPending) return <Typography>Loading members…</Typography>
  if (list.isError) return <LoadError what="the members" error={list.error} onRetry={() => void list.refetch()} />
  const { count, results } = list.data
  if (count === 0) return <Typography>This lab has no members yet.</Typography>
  if (results.length === 0) return <PastTheEnd onFirstPage={() => onOffsetChange(0)} />
  return (
    <section aria-label="Members" aria-busy={list.isPlaceholderData}>
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
                      <Button size="small" aria-label={`Change role of ${member.username}`} onClick={() => setOpen({ kind: 'role', member })}>
                        Change role
                      </Button>
                      <Button size="small" color="error" aria-label={`Remove ${member.username}`} onClick={() => setOpen({ kind: 'remove', member })}>
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
      {open?.kind === 'role' && <ChangeRoleDialog labId={labId} member={open.member} roles={grantable} onClose={() => setOpen(null)} />}
      {open?.kind === 'remove' && <RemoveMemberDialog labId={labId} labName={labName} member={open.member} onClose={() => setOpen(null)} />}
    </section>
  )
}
