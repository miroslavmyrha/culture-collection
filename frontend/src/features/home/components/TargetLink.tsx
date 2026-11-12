import type { ReactNode } from 'react'
import { Link } from '@/components/ui'
import type { ActivityLine, WaitingItem } from '../schemas'

type Target = WaitingItem['target'] | NonNullable<ActivityLine['target']>

type LabTarget = 'lab' | 'permits' | 'requesters'
type ItemTarget = Exclude<Target, LabTarget>

/** The pages of a lab as a whole: no id needed. */
const LAB_LINKS: Record<LabTarget, (labId: string, children: ReactNode) => ReactNode> = {
  lab: (labId, children) => (
    <Link to="/labs/$labId" params={{ labId }}>
      {children}
    </Link>
  ),
  permits: (labId, children) => (
    <Link to="/labs/$labId/permits" params={{ labId }}>
      {children}
    </Link>
  ),
  requesters: (labId, children) => (
    <Link to="/labs/$labId/requesters" params={{ labId }}>
      {children}
    </Link>
  ),
}

/** The page of one thing in a lab. A strain with a vial opens its Material tab narrowed to that vial. */
const ITEM_LINKS: Record<ItemTarget, (labId: string, id: string, vial: string | null, children: ReactNode) => ReactNode> = {
  deposit: (labId, id, _vial, children) => (
    <Link to="/labs/$labId/deposits/$depositId" params={{ labId, depositId: id }}>
      {children}
    </Link>
  ),
  strain: (labId, id, vial, children) =>
    vial === null ? (
      <Link to="/labs/$labId/strains/$strainId" params={{ labId, strainId: id }}>
        {children}
      </Link>
    ) : (
      <Link to="/labs/$labId/strains/$strainId/material" params={{ labId, strainId: id }} search={{ vial }}>
        {children}
      </Link>
    ),
  request: (labId, id, _vial, children) => (
    <Link to="/labs/$labId/requests/$requestId" params={{ labId, requestId: id }}>
      {children}
    </Link>
  ),
  storage_unit: (labId, id, _vial, children) => (
    <Link to="/labs/$labId/storage/$unitId" params={{ labId, unitId: id }}>
      {children}
    </Link>
  ),
  mta_template: (labId, id, _vial, children) => (
    <Link to="/labs/$labId/mta-templates/$templateId" params={{ labId, templateId: id }}>
      {children}
    </Link>
  ),
}

const isLabTarget = (target: Target): target is LabTarget => target in LAB_LINKS

/**
 * The page where an item of Home is handled or a line's subject lives, from the server's target
 * and ids; a strain with a vial opens its Material tab narrowed to that vial. A target that needs an id and has none, or no target, renders the words alone.
 */
export function TargetLink({
  labId,
  target,
  id,
  vial = null,
  children,
}: {
  labId: string
  target: Target | null
  id: string | null
  /** With a strain: the vial its Material tab narrows to (#159). */
  vial?: string | null
  children: ReactNode
}) {
  if (target !== null && isLabTarget(target)) return LAB_LINKS[target](labId, children)
  if (target === null || id === null) return <>{children}</>
  return ITEM_LINKS[target](labId, id, vial, children)
}
