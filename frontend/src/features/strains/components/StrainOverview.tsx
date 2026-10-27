import { type MouseEvent, useRef, useState } from 'react'
import { Box, Button, Link, Stack, StatusChip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { ATMOSPHERE_LABELS, temperatureText } from '@/lib/growth'
import { STRAIN_TONES } from '@/lib/tones'
import {
  CAUSE_LABELS,
  countryName,
  type DeaccessionProposal,
  FINAL_USE_LABELS,
  GMO_CATEGORY_LABELS,
  PATHOGENICITY_LABELS,
  RESTRICTION_LABELS,
  STATUS_LABELS,
  type Strain,
} from '../schemas'
import { day, Facts, scrollable, Section } from './parts'
import { ConfirmDeaccessionDialog, ConfirmEndDialog, ProposeEndDialog, WithdrawDeaccessionDialog, WithdrawEndDialog } from './StrainDialogs'
import { StrainShipments } from './StrainShipments'
import { ActiveTerms } from './StrainTerms'

type Props = { labId: string; strain: Strain; canManage: boolean; canConfirm: boolean; canConfirmLeave?: boolean }
type Settle = { step: 'confirm' | 'withdraw'; proposal: DeaccessionProposal; open: boolean } | null

type Restriction = Strain['restriction_history'][number]
type Step = 'propose' | 'confirm' | 'withdraw'
type Open = { step: Step; restriction: Restriction; open: boolean } | null
type Act = (step: Step, r: Restriction) => (event: MouseEvent<HTMLButtonElement>) => void

/**
 * What the strain is (#19): its facts, its restrictions, the terms of use in force and how it was
 * identified, from the strain the page already holds; only the terms are a read of their own.
 */
export function StrainOverview({ labId, strain: s, canManage, canConfirm, canConfirmLeave = false }: Props) {
  const [open, setOpen] = useState<Open>(null)
  const [settling, setSettling] = useState<Settle>(null)
  const spot = useRef<FocusReturn | null>(null)
  const act: Act = (step, restriction) => (event) => {
    spot.current = rememberFocus(event.currentTarget)
    setOpen({ step, restriction, open: true })
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
    setSettling(null)
  }
  const settle = (step: 'confirm' | 'withdraw', proposal: DeaccessionProposal) => (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    setSettling({ step, proposal, open: true })
  }
  const closeSettling = () => setSettling((current) => current && { ...current, open: false })
  const active = s.restriction_history.filter((r) => r.ended_at === null)
  const ended = s.restriction_history.filter((r) => r.ended_at !== null)
  return (
    <>
      {s.deaccession && (
        <Section title="Deaccession">
          <Facts
            rows={[
              ['Left the collection', day(s.deaccession.deaccessioned_at)],
              ['Cause', CAUSE_LABELS[s.deaccession.cause]],
              ['Reason', s.deaccession.reason],
              ...(s.deaccession.final_use ? [['Final use', FINAL_USE_LABELS[s.deaccession.final_use]] as [string, string]] : []),
            ]}
          />
          <Typography>Its number is never given to another strain, and its history stays.</Typography>
        </Section>
      )}
      {s.deaccession_proposal && (
        <ProposedDeaccession proposal={s.deaccession_proposal} canManage={canManage} canConfirm={canConfirmLeave} onSettle={settle} />
      )}
      {s.deaccession && <StrainShipments labId={labId} strainId={s.public_id} />}

      <Section title="Facts">
        <Facts
          rows={[
            ['Name as received', s.name_as_received],
            ['Status', <StatusChip key="status" tone={STRAIN_TONES[s.status]}>{STATUS_LABELS[s.status]}</StatusChip>],
            ['Risk group', String(s.risk_group)],
            ['Animal pathogenicity', PATHOGENICITY_LABELS[s.animal_pathogenicity]],
            ['Plant pathogenicity', PATHOGENICITY_LABELS[s.plant_pathogenicity]],
            ['Isolation source', s.isolation_source || 'Unknown'],
            ['Country of origin', s.country_of_origin ? countryName(s.country_of_origin) : 'Unknown'],
            ['Isolation date', s.isolation_date || 'Unknown'],
            ['Accessioned', day(s.created_at)],
          ]}
        />
      </Section>

      <Section title="Growth conditions">
        <Facts
          rows={[
            ['Medium', s.growth.medium ? `${s.growth.medium.name}${s.growth.medium.composition_reference ? `, ${s.growth.medium.composition_reference}` : ''}${s.growth.medium.retired_at ? ' (retired)' : ''}` : 'Not recorded'],
            ['Temperature', temperatureText(s.growth) || 'Not recorded'],
            ['Atmosphere', s.growth.atmosphere ? ATMOSPHERE_LABELS[s.growth.atmosphere] : 'Not recorded'],
          ]}
        />
      </Section>

      <Section title="Restrictions">
        {active.length === 0 ? (
          <Typography>None. The agent is on no regulatory list.</Typography>
        ) : (
          <RestrictionTable rows={active} caption="Current restrictions" act={canManage || canConfirm ? act : undefined} canManage={canManage} canConfirm={canConfirm} />
        )}
        {ended.length > 0 && <RestrictionTable rows={ended} caption="Ended restrictions" />}
      </Section>

      <Section title="Terms of use">
        <ActiveTerms labId={labId} strainId={s.public_id} />
        <Typography>
          <Link to="/labs/$labId/strains/$strainId/terms" params={{ labId, strainId: s.public_id }}>
            Every version of the terms
          </Link>
        </Typography>
      </Section>

      <Section title="Identification history">
        <TableContainer {...scrollable('Identification history')}>
          <Table aria-label="Identification history">
            <TableHead>
              <TableRow>
                <TableCell>Identified on</TableCell>
                <TableCell>Taxon</TableCell>
                <TableCell>Method</TableCell>
                <TableCell>Reason</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {s.identifications.map((i) => (
                <TableRow key={i.public_id}>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>
                    {i.identified_on}
                    {i.is_current && <Box component="span"> (current)</Box>}
                  </TableCell>
                  <TableCell>
                    <i>{i.taxon.name}</i> {i.taxon.authority}
                  </TableCell>
                  <TableCell>{i.method}</TableCell>
                  <TableCell>{i.reason}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Section>

      {/* Mounted until it has faded out, so onExited can place the focus. */}
      {open && <EndDialog labId={labId} strain={s} at={open} onClose={close} onExited={exited} />}
      {settling?.step === 'confirm' && (
        <ConfirmDeaccessionDialog labId={labId} strain={s} proposal={settling.proposal} open={settling.open} onClose={closeSettling} onExited={exited} />
      )}
      {settling?.step === 'withdraw' && (
        <WithdrawDeaccessionDialog labId={labId} strain={s} proposal={settling.proposal} open={settling.open} onClose={closeSettling} onExited={exited} />
      )}
    </>
  )
}

function EndDialog({ labId, strain, at, onClose, onExited }: { labId: string; strain: Strain; at: NonNullable<Open>; onClose: () => void; onExited: () => void }) {
  const common = { labId, strain, restriction: at.restriction, open: at.open, onClose, onExited }
  const proposal = at.restriction.end_proposal
  if (at.step === 'propose' || proposal === null) return <ProposeEndDialog {...common} />
  if (at.step === 'confirm') return <ConfirmEndDialog {...common} proposal={proposal} />
  return <WithdrawEndDialog {...common} proposal={proposal} />
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
            <TableRow key={r.public_id}>
              <TableCell>
                <StatusChip tone="regulated">{RESTRICTION_LABELS[r.kind]}</StatusChip>
              </TableCell>
              <TableCell sx={{ overflowWrap: 'anywhere' }}>
                {r.reference}
                {r.act && ` (read in ${r.act})`}
                {r.gmo_category !== null && `, category ${GMO_CATEGORY_LABELS[r.gmo_category] ?? r.gmo_category}`}
              </TableCell>
              <TableCell sx={{ whiteSpace: 'nowrap' }}>{day(r.created_at)}</TableCell>
              {isEnded && (
                <TableCell>
                  {r.ended_at && day(r.ended_at)}: {r.end_reason}
                </TableCell>
              )}
              {isProposed && <TableCell>{r.end_proposal && <Proposed proposal={r.end_proposal} canConfirm={canConfirm} />}</TableCell>}
              {act && (
                <TableCell>
                  <Actions restriction={r} act={act} canManage={canManage} canConfirm={canConfirm} />
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

/** A proposal waiting for a second person (#105): what it says and who may settle it. */
function Proposed({ proposal, canConfirm }: { proposal: NonNullable<Restriction['end_proposal']>; canConfirm: boolean }) {
  const own = proposal.confirm_refusal === 'confirm_own_end_proposal'
  return (
    <>
      Proposed {day(proposal.proposed_at)}: {proposal.reason}
      <Typography variant="body2" color="text.secondary">
        {own ? 'You proposed it: a different manager confirms.' : canConfirm ? 'Waiting for your confirmation.' : 'Waiting for a manager to confirm.'}
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

type ProposedProps = {
  proposal: DeaccessionProposal
  canManage: boolean
  canConfirm: boolean
  onSettle: (step: 'confirm' | 'withdraw', proposal: DeaccessionProposal) => (event: MouseEvent<HTMLButtonElement>) => void
}

/** A proposal to deaccession the regulated strain, waiting for a second person (#20). */
function ProposedDeaccession({ proposal, canManage, canConfirm, onSettle }: ProposedProps) {
  const own = proposal.confirm_refusal === 'confirm_own_deaccession'
  return (
    <Section title="Proposed deaccession">
      <Facts
        rows={[
          ['Proposed', day(proposal.proposed_at)],
          ['Cause', CAUSE_LABELS[proposal.cause]],
          ['Reason', proposal.reason],
          ...(proposal.final_use ? [['Final use', FINAL_USE_LABELS[proposal.final_use]] as [string, string]] : []),
        ]}
      />
      <Typography color="text.secondary">
        {own ? 'You proposed it: a different manager confirms.' : canConfirm ? 'Waiting for your confirmation.' : 'Waiting for a manager to confirm.'}
      </Typography>
      {(canManage || canConfirm) && (
        <Stack direction="row" spacing={1}>
          {canConfirm && !own && <Button onClick={onSettle('confirm', proposal)}>Confirm deaccession</Button>}
          {canManage && <Button onClick={onSettle('withdraw', proposal)}>Withdraw the proposal</Button>}
        </Stack>
      )}
    </Section>
  )
}
