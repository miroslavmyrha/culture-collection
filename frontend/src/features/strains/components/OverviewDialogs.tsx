import type { Strain } from '../schemas'
import type { OpenEnd, OverviewDialogs as State } from './useOverviewDialogs'
import {
  ConfirmDeaccessionDialog,
  ConfirmEndDialog,
  ConfirmRiskGroupDialog,
  ProposeEndDialog,
  WithdrawDeaccessionDialog,
  WithdrawEndDialog,
  WithdrawRiskGroupDialog,
} from './StrainDialogs'

type Props = { labId: string; strain: Strain; dialogs: State }

/** The dialog the person opened on the overview, if any. */
export function OverviewDialogs({ labId, strain, dialogs }: Props) {
  const { open, settling, settlingRisk, exited } = dialogs
  return (
    <>
      {open && <EndDialog labId={labId} strain={strain} at={open} onClose={dialogs.close} onExited={exited} />}
      <DeaccessionDialog labId={labId} strain={strain} settling={settling} onClose={dialogs.closeSettling} onExited={exited} />
      <RiskGroupDialog labId={labId} strain={strain} settling={settlingRisk} onClose={dialogs.closeSettlingRisk} onExited={exited} />
    </>
  )
}

function EndDialog({ labId, strain, at, onClose, onExited }: { labId: string; strain: Strain; at: NonNullable<OpenEnd>; onClose: () => void; onExited: () => void }) {
  const common = { labId, strain, restriction: at.restriction, open: at.open, onClose, onExited }
  const proposal = at.restriction.end_proposal
  if (at.step === 'propose' || proposal === null) return <ProposeEndDialog {...common} />
  if (at.step === 'confirm') return <ConfirmEndDialog {...common} proposal={proposal} />
  return <WithdrawEndDialog {...common} proposal={proposal} />
}

type SettleProps = { labId: string; strain: Strain; settling: State['settling']; onClose: () => void; onExited: () => void }

function DeaccessionDialog({ labId, strain, settling, onClose, onExited }: SettleProps) {
  if (!settling) return null
  const props = { labId, strain, proposal: settling.proposal, open: settling.open, onClose, onExited }
  return settling.step === 'confirm' ? <ConfirmDeaccessionDialog {...props} /> : <WithdrawDeaccessionDialog {...props} />
}

type RiskProps = Omit<SettleProps, 'settling'> & { settling: State['settlingRisk'] }

function RiskGroupDialog({ labId, strain, settling, onClose, onExited }: RiskProps) {
  if (!settling) return null
  const props = { labId, strain, proposal: settling.proposal, open: settling.open, onClose, onExited }
  return settling.step === 'confirm' ? <ConfirmRiskGroupDialog {...props} /> : <WithdrawRiskGroupDialog {...props} />
}
