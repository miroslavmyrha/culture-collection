import { type MouseEvent, useRef, useState } from 'react'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import type { DeaccessionProposal, RiskGroupProposal } from '../schemas'
import type { Restriction, Step } from './RestrictionsSection'

type Settling<P> = { step: 'confirm' | 'withdraw'; proposal: P; open: boolean } | null
export type OpenEnd = { step: Step; restriction: Restriction; open: boolean } | null

/**
 * Which of the overview's dialogs is open: ending a restriction, settling a deaccession proposal
 * or settling a risk group proposal. One focus spot serves all three, and the dialogs stay
 * mounted until they have faded out, so onExited can place the focus.
 */
export function useOverviewDialogs() {
  const [open, setOpen] = useState<OpenEnd>(null)
  const [settling, setSettling] = useState<Settling<DeaccessionProposal>>(null)
  const [settlingRisk, setSettlingRisk] = useState<Settling<RiskGroupProposal>>(null)
  const spot = useRef<FocusReturn | null>(null)
  const remember = (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
  }
  return {
    open,
    settling,
    settlingRisk,
    act: (step: Step, restriction: Restriction) => (event: MouseEvent<HTMLButtonElement>) => {
      remember(event)
      setOpen({ step, restriction, open: true })
    },
    settle: (step: 'confirm' | 'withdraw', proposal: DeaccessionProposal) => (event: MouseEvent<HTMLButtonElement>) => {
      remember(event)
      setSettling({ step, proposal, open: true })
    },
    settleRisk: (step: 'confirm' | 'withdraw', proposal: RiskGroupProposal) => (event: MouseEvent<HTMLButtonElement>) => {
      remember(event)
      setSettlingRisk({ step, proposal, open: true })
    },
    close: () => setOpen((current) => current && { ...current, open: false }),
    closeSettling: () => setSettling((current) => current && { ...current, open: false }),
    closeSettlingRisk: () => setSettlingRisk((current) => current && { ...current, open: false }),
    exited: () => {
      spot.current?.restore()
      spot.current = null
      setOpen(null)
      setSettling(null)
      setSettlingRisk(null)
    },
  }
}

export type OverviewDialogs = ReturnType<typeof useOverviewDialogs>
