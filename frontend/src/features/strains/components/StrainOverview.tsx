import { type Strain } from '../schemas'
import { DeaccessionSection, FactsSection, GrowthSection, IdentificationSection, TermsSection } from './OverviewSections'
import { OverviewDialogs } from './OverviewDialogs'
import { ProposedDeaccession, ProposedRiskGroup } from './ProposalSections'
import { RestrictionsSection } from './RestrictionsSection'
import { StrainListMatches } from './StrainListMatches'
import { StrainShipments } from './StrainShipments'
import { useOverviewDialogs } from './useOverviewDialogs'

type Props = {
  labId: string
  strain: Strain
  canManage: boolean
  canConfirm: boolean
  canConfirmLeave?: boolean
  canConfirmRisk?: boolean
}

/**
 * What the strain is (#19): its facts, its restrictions, the terms of use in force and how it was
 * identified, from the strain the page already holds; only the terms are a read of their own.
 */
export function StrainOverview({ labId, strain: s, canManage, canConfirm, canConfirmLeave = false, canConfirmRisk = false }: Props) {
  const dialogs = useOverviewDialogs()
  return (
    <>
      {s.deaccession && <DeaccessionSection deaccession={s.deaccession} />}
      {s.deaccession_proposal && <ProposedDeaccession proposal={s.deaccession_proposal} canManage={canManage} canConfirm={canConfirmLeave} onSettle={dialogs.settle} />}
      {s.deaccession && <StrainShipments labId={labId} strainId={s.public_id} />}
      {s.risk_group_proposal && <ProposedRiskGroup proposal={s.risk_group_proposal} canManage={canManage} canConfirm={canConfirmRisk} onSettle={dialogs.settleRisk} />}
      <FactsSection labId={labId} strain={s} />
      <GrowthSection growth={s.growth} />
      <RestrictionsSection history={s.restriction_history} act={dialogs.act} canManage={canManage} canConfirm={canConfirm} />
      <TermsSection labId={labId} strainId={s.public_id} />
      <IdentificationSection identifications={s.identifications} />
      <StrainListMatches labId={labId} strain={s} canManage={canManage} />

      {/* Mounted until it has faded out, so onExited can place the focus. */}
      <OverviewDialogs labId={labId} strain={s} dialogs={dialogs} />
    </>
  )
}
