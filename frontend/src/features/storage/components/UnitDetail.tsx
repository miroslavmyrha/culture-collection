import { type MouseEvent, type ReactNode, useRef, useState } from 'react'
import { StaleNotice } from '@/components/StaleNotice'
import { PageTitle } from '@/components/ui'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { useUnit } from '../api/queries'
import { HOLDS, type Unit } from '../schemas'
import { UnitActions, type UnitAction } from './UnitActions'
import { CreateUnitDialog, EditUnitDialog, MoveUnitDialog, UnitStatusDialog } from './UnitDialogs'
import { UnitFacts } from './UnitFacts'
import { UnitHeader } from './UnitHeader'
import { UnitHolds } from './UnitHolds'
import { UnitUnavailable } from './UnitStates'

type Props = {
  labId: string
  labName: string
  unitId: string
  canManage: boolean
  /** After a unit is added inside this one: show it. */
  onCreated: (unit: Unit) => void
  /** What the unit holds besides units (a box's positions), from the page: features do not import each other. */
  renderContents?: (unit: Unit) => ReactNode
}

type Open = { kind: UnitAction; open: boolean } | null

/** One storage unit: where it is (breadcrumbs), what it is, what it holds, and for curators the actions. */
export function UnitDetail({ labId, labName, unitId, canManage, onCreated, renderContents }: Props) {
  const unit = useUnit(labId, unitId)
  const [open, setOpen] = useState<Open>(null)
  const spot = useRef<FocusReturn | null>(null)
  const show = (kind: UnitAction) => (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    setOpen({ kind, open: true })
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }

  if (unit.data === undefined) return <UnitUnavailable unit={unit} />
  const u = unit.data
  const above = u.ancestors.at(-1)
  return (
    <>
      <PageTitle>{above ? `${u.name} in ${above.name}` : u.name}</PageTitle>
      <UnitHeader labId={labId} labName={labName} unit={u} />
      <StaleNotice what="the unit" query={unit} />
      <UnitFacts unit={u} />
      <UnitActions unit={u} canManage={canManage} show={show} />
      {HOLDS[u.kind].length > 0 && <UnitHolds labId={labId} unit={u} />}

      {renderContents?.(u)}

      {/* Mounted until they have faded out, so onExited can place the focus. */}
      <OpenUnitDialog open={open} labId={labId} unit={u} onClose={close} onExited={exited} onCreated={onCreated} />
    </>
  )
}

type DialogProps = { open: Open; labId: string; unit: Unit; onClose: () => void; onExited: () => void; onCreated: (unit: Unit) => void }

/** The dialog the person opened, if any: one of add, change, move or the three states. */
function OpenUnitDialog({ open, labId, unit, onClose, onExited, onCreated }: DialogProps) {
  if (open === null) return null
  const common = { labId, open: open.open, onClose, onExited }
  if (open.kind === 'add') return <CreateUnitDialog {...common} parent={unit} onCreated={onCreated} />
  if (open.kind === 'edit') return <EditUnitDialog {...common} unit={unit} />
  if (open.kind === 'move') return <MoveUnitDialog {...common} unit={unit} />
  return <UnitStatusDialog {...common} unit={unit} to={open.kind} />
}
