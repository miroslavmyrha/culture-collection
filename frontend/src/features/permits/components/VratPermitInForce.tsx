import { Typography } from '@/components/ui'
import { usePermitList } from '../api/queries'

/**
 * The lab's SÚJB permits for highly risky agents (VRAT) in force today, as one line for a printed
 * page: the issuer, the reference, from when, and the last valid day when the permit states one.
 * "None in force" when the lab holds none today (expired, ended, not valid yet or never recorded).
 */
export function VratPermitInForce({ labId }: { labId: string }) {
  const list = usePermitList(labId)
  if (list.data === undefined) {
    if (list.isPending) return <>Loading the permits…</>
    return <Typography component="span">Could not load the permits.</Typography>
  }
  const held = list.data.filter((p) => p.kind === 'cz_vrat' && (p.standing === 'valid' || p.standing === 'expires_soon'))
  if (held.length === 0) return <>None in force on record</>
  return (
    <>
      {held
        .map((p) => `${p.issuer_label} ${p.permit_reference}, valid from ${p.valid_from}${p.last_valid_day ? ` until ${p.last_valid_day}` : ''}`)
        .join('; ')}
    </>
  )
}
