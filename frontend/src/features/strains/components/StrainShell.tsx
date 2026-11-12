import { type ReactNode, useRef, useState } from 'react'
import { StaleNotice } from '@/components/StaleNotice'
import type { ActionItem } from '@/components/ui'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { useStrain } from '../api/queries'
import type { Strain } from '../schemas'
import { AddRestrictionDialog, DeaccessionDialog, GrowthDialog, ProposeDeaccessionDialog, ReclassifyDialog, RiskGroupDialog } from './StrainDialogs'
import { StrainHeader, StrainUnavailable } from './StrainShellParts'

type Props = {
  labId: string
  strainId: string
  canManage: boolean
  /** The tabs and the open tab, rendered once the strain is there. */
  children: (strain: Strain) => ReactNode
}

type Kind = 'reclassify' | 'risk' | 'add' | 'growth' | 'leave' | 'propose-leave'
type Open = { kind: Kind; open: boolean } | null

/** A regulated strain leaves by two people (#20): the menu proposes it, unless a proposal waits. */
function leaveItems(s: Strain, show: (kind: Kind) => (button: HTMLButtonElement) => void): ActionItem[] {
  if (s.deaccession_proposal !== null) return []
  return [{ label: s.regulated ? 'Propose deaccession' : 'Deaccession', onSelect: show(s.regulated ? 'propose-leave' : 'leave') }]
}

/**
 * A strain's page around its tabs (#19): the strain's loading, not found and error states, each
 * with its title, and once it is there the header every tab shares: the accession number, the
 * taxon, the risk group, the active restrictions and the status as chips, and the strain's
 * actions in one menu for curators and up. A deaccessioned strain changes no more and has no
 * menu (#20). The tab renders the page title.
 */
export function StrainShell({ labId, strainId, canManage, children }: Props) {
  const strain = useStrain(labId, strainId)
  const [open, setOpen] = useState<Open>(null)
  const spot = useRef<FocusReturn | null>(null)
  const show = (kind: Kind) => (button: HTMLButtonElement) => {
    spot.current = rememberFocus(button)
    setOpen({ kind, open: true })
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }

  if (strain.data === undefined) return <StrainUnavailable strain={strain} />
  const s = strain.data
  const actions = canManage && s.status !== 'deaccessioned' ? menuItems(s, show) : null
  return (
    <>
      <StrainHeader strain={s} actions={actions} />
      <StaleNotice what="the strain" query={strain} />
      {children(s)}

      {/* Mounted until they have faded out, so onExited can place the focus. */}
      <ShellDialog open={open} labId={labId} strain={s} onClose={close} onExited={exited} />
    </>
  )
}

function menuItems(s: Strain, show: (kind: Kind) => (button: HTMLButtonElement) => void): ActionItem[] {
  return [
    { label: 'Reclassify', onSelect: show('reclassify') },
    { label: 'Change risk group', onSelect: show('risk') },
    { label: 'Add a restriction', onSelect: show('add') },
    { label: 'Change growth conditions', onSelect: show('growth') },
    ...leaveItems(s, show),
  ]
}

type DialogProps = { open: Open; labId: string; strain: Strain; onClose: () => void; onExited: () => void }

/** The dialog the person opened from the actions menu, if any. */
function ShellDialog({ open, labId, strain, onClose, onExited }: DialogProps) {
  if (open === null) return null
  const props = { labId, strain, open: open.open, onClose, onExited }
  if (open.kind === 'reclassify') return <ReclassifyDialog {...props} />
  if (open.kind === 'risk') return <RiskGroupDialog {...props} />
  if (open.kind === 'growth') return <GrowthDialog {...props} />
  if (open.kind === 'add') return <AddRestrictionDialog {...props} />
  if (open.kind === 'leave') return <DeaccessionDialog {...props} />
  return <ProposeDeaccessionDialog {...props} />
}
