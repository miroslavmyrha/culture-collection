import type { MouseEvent } from 'react'
import { Button, Stack, Typography } from '@/components/ui'
import { CAUSE_LABELS, type DeaccessionProposal, type RiskGroupProposal } from '../schemas'
import { finalUseRows } from './OverviewSections'
import { day, Facts, Section } from './parts'

type Settle<P> = (step: 'confirm' | 'withdraw', proposal: P) => (event: MouseEvent<HTMLButtonElement>) => void

/** What a proposal waits for: a different manager, or you if you may confirm. */
export function waitingText(own: boolean, canConfirm: boolean): string {
  if (own) return 'You proposed it: a different manager confirms.'
  return canConfirm ? 'Waiting for your confirmation.' : 'Waiting for a manager to confirm.'
}

type SettleProps<P> = {
  proposal: P
  own: boolean
  canManage: boolean
  canConfirm: boolean
  confirmLabel: string
  onSettle: Settle<P>
}

/** Confirm (a second person, never the proposer) and withdraw (a manager) for a proposal. */
function SettleButtons<P>({ proposal, own, canManage, canConfirm, confirmLabel, onSettle }: SettleProps<P>) {
  if (!canManage && !canConfirm) return null
  return (
    <Stack direction="row" spacing={1}>
      {canConfirm && !own && <Button onClick={onSettle('confirm', proposal)}>{confirmLabel}</Button>}
      {canManage && <Button onClick={onSettle('withdraw', proposal)}>Withdraw the proposal</Button>}
    </Stack>
  )
}

type ProposedProps<P> = {
  proposal: P
  canManage: boolean
  canConfirm: boolean
  onSettle: Settle<P>
}

/** A proposal to deaccession the regulated strain, waiting for a second person (#20). */
export function ProposedDeaccession({ proposal, canManage, canConfirm, onSettle }: ProposedProps<DeaccessionProposal>) {
  const own = proposal.confirm_refusal === 'confirm_own_deaccession'
  return (
    <Section title="Proposed deaccession">
      <Facts rows={[['Proposed', day(proposal.proposed_at)], ['Cause', CAUSE_LABELS[proposal.cause]], ['Reason', proposal.reason], ...finalUseRows(proposal.final_use)]} />
      <Typography color="text.secondary">{waitingText(own, canConfirm)}</Typography>
      <SettleButtons proposal={proposal} own={own} canManage={canManage} canConfirm={canConfirm} confirmLabel="Confirm deaccession" onSettle={onSettle} />
    </Section>
  )
}

/** A proposal to lower the strain's risk group, waiting for a second person (#174). */
export function ProposedRiskGroup({ proposal, canManage, canConfirm, onSettle }: ProposedProps<RiskGroupProposal>) {
  const own = proposal.confirm_refusal === 'confirm_own_risk_group'
  return (
    <Section title="Proposed risk group">
      <Facts
        rows={[
          ['Proposed', day(proposal.proposed_at)],
          ['New risk group', `${proposal.risk_group}, down from ${proposal.from_risk_group}`],
          ['Basis', proposal.basis],
          ['Reason', proposal.reason],
        ]}
      />
      <Typography color="text.secondary">{waitingText(own, canConfirm)}</Typography>
      <Typography>Until then every rule reads the risk group the strain has now.</Typography>
      <SettleButtons proposal={proposal} own={own} canManage={canManage} canConfirm={canConfirm} confirmLabel="Confirm the lower risk group" onSettle={onSettle} />
    </Section>
  )
}
