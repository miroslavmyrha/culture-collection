import type { MouseEvent } from 'react'
import { Button, Stack, StatusChip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { GMO_CATEGORY_LABELS, RESTRICTION_LABELS, type Strain } from '../schemas'
import { day, scrollable, Section } from './parts'
import { waitingText } from './ProposalSections'

export type Restriction = Strain['restriction_history'][number]
export type Step = 'propose' | 'confirm' | 'withdraw'
export type Act = (step: Step, r: Restriction) => (event: MouseEvent<HTMLButtonElement>) => void

type Props = { history: Strain['restriction_history']; act: Act; canManage: boolean; canConfirm: boolean }

/** The restrictions in force, with what a manager may do to each, and the ended ones. */
export function RestrictionsSection({ history, act, canManage, canConfirm }: Props) {
  const active = history.filter((r) => r.ended_at === null)
  const ended = history.filter((r) => r.ended_at !== null)
  return (
    <Section title="Restrictions">
      {active.length === 0 ? (
        <Typography>None. The agent is on no regulatory list.</Typography>
      ) : (
        <RestrictionTable rows={active} caption="Current restrictions" act={canManage || canConfirm ? act : undefined} canManage={canManage} canConfirm={canConfirm} />
      )}
      {ended.length > 0 && <RestrictionTable rows={ended} caption="Ended restrictions" />}
    </Section>
  )
}

type TableProps = {
  rows: Restriction[]
  caption: string
  act?: Act | undefined
  canManage?: boolean
  canConfirm?: boolean
}

function RestrictionTable({ rows, caption, act, canManage = false, canConfirm = false }: TableProps) {
  const isEnded = rows.some((r) => r.ended_at !== null)
  const isProposed = rows.some((r) => r.end_proposal !== null)
  return (
    <TableContainer {...scrollable(caption)}>
      <Table aria-label={caption}>
        <TableHead>
          <TableRow>
            <TableCell>Kind</TableCell>
            <TableCell>List entry</TableCell>
            <TableCell>Since</TableCell>
            {isEnded && <TableCell>Ended</TableCell>}
            {isProposed && <TableCell>Ending</TableCell>}
            {act && <TableCell>Action</TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((r) => (
            <RestrictionRow key={r.public_id} restriction={r} columns={{ ended: isEnded, proposed: isProposed }} act={act} canManage={canManage} canConfirm={canConfirm} />
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

type RowProps = {
  restriction: Restriction
  /** Which of the optional columns the table has. */
  columns: { ended: boolean; proposed: boolean }
  act: Act | undefined
  canManage: boolean
  canConfirm: boolean
}

/** Where the restriction is read, with the act and the GMO category when it has them. */
function entryText(r: Restriction): string {
  const act = r.act ? ` (read in ${r.act})` : ''
  const category = r.gmo_category === null ? '' : `, category ${GMO_CATEGORY_LABELS[r.gmo_category] ?? r.gmo_category}`
  return `${r.reference}${act}${category}`
}

function RestrictionRow({ restriction: r, columns, act, canManage, canConfirm }: RowProps) {
  return (
    <TableRow>
      <TableCell>
        <StatusChip tone="regulated">{RESTRICTION_LABELS[r.kind]}</StatusChip>
      </TableCell>
      <TableCell sx={{ overflowWrap: 'anywhere' }}>{entryText(r)}</TableCell>
      <TableCell sx={{ whiteSpace: 'nowrap' }}>{day(r.created_at)}</TableCell>
      {columns.ended && (
        <TableCell>
          {r.ended_at && day(r.ended_at)}: {r.end_reason}
        </TableCell>
      )}
      {columns.proposed && <TableCell>{r.end_proposal && <Proposed proposal={r.end_proposal} canConfirm={canConfirm} />}</TableCell>}
      {act && (
        <TableCell>
          <Actions restriction={r} act={act} canManage={canManage} canConfirm={canConfirm} />
        </TableCell>
      )}
    </TableRow>
  )
}

/** A proposal waiting for a second person (#105): what it says and who may settle it. */
function Proposed({ proposal, canConfirm }: { proposal: NonNullable<Restriction['end_proposal']>; canConfirm: boolean }) {
  const own = proposal.confirm_refusal === 'confirm_own_end_proposal'
  return (
    <>
      Proposed {day(proposal.proposed_at)}: {proposal.reason}
      <Typography variant="body2" color="text.secondary">
        {waitingText(own, canConfirm)}
      </Typography>
    </>
  )
}

function Actions({ restriction: r, act, canManage, canConfirm }: { restriction: Restriction; act: Act; canManage: boolean; canConfirm: boolean }) {
  const proposal = r.end_proposal
  if (proposal === null) {
    return canManage ? (
      <Button onClick={act('propose', r)} aria-label={`Propose to end restriction ${r.reference}`}>
        Propose to end
      </Button>
    ) : null
  }
  return (
    <Stack direction="row" spacing={1}>
      {canConfirm && proposal.confirm_refusal === null && (
        <Button onClick={act('confirm', r)} aria-label={`Confirm the end of restriction ${r.reference}`}>
          Confirm end
        </Button>
      )}
      {canManage && (
        <Button onClick={act('withdraw', r)} aria-label={`Withdraw the proposal to end restriction ${r.reference}`}>
          Withdraw
        </Button>
      )}
    </Stack>
  )
}
