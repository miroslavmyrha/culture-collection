import type { ReactNode } from 'react'
import { Link } from '@/components/ui'
import type { ActivityLine, WaitingItem } from '../schemas'

type Target = WaitingItem['target'] | NonNullable<ActivityLine['target']>

/**
 * The page where an item of Home is handled or a line's subject lives, from the server's target
 * and ids. A target that needs an id and has none, or no target, renders the words alone.
 */
export function TargetLink({ labId, target, id, children }: { labId: string; target: Target | null; id: string | null; children: ReactNode }) {
  if (target === 'lab') {
    return (
      <Link to="/labs/$labId" params={{ labId }}>
        {children}
      </Link>
    )
  }
  if (target === 'requesters') {
    return (
      <Link to="/labs/$labId/requesters" params={{ labId }}>
        {children}
      </Link>
    )
  }
  if (target === null || id === null) return <>{children}</>
  if (target === 'deposit') {
    return (
      <Link to="/labs/$labId/deposits/$depositId" params={{ labId, depositId: id }}>
        {children}
      </Link>
    )
  }
  if (target === 'strain') {
    return (
      <Link to="/labs/$labId/strains/$strainId" params={{ labId, strainId: id }}>
        {children}
      </Link>
    )
  }
  if (target === 'request') {
    return (
      <Link to="/labs/$labId/requests/$requestId" params={{ labId, requestId: id }}>
        {children}
      </Link>
    )
  }
  if (target === 'storage_unit') {
    return (
      <Link to="/labs/$labId/storage/$unitId" params={{ labId, unitId: id }}>
        {children}
      </Link>
    )
  }
  // The last target left: a new one fails to compile here.
  void (target satisfies 'mta_template')
  return (
    <Link to="/labs/$labId/mta-templates/$templateId" params={{ labId, templateId: id }}>
      {children}
    </Link>
  )
}
