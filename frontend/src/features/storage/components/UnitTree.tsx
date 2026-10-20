import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Typography } from '@/components/ui'
import { useUnitTree } from '../api/queries'
import { StorageTree } from './StorageTree'

type Props = { labId: string; labName: string; canManage: boolean; onOpen: (unitId: string) => void }

/** The lab's storage tree with its loading, error and empty states. */
export function UnitTree({ labId, labName, canManage, onOpen }: Props) {
  const tree = useUnitTree(labId)
  if (tree.data === undefined) {
    if (tree.isPending) return <Typography aria-busy>Loading the storage…</Typography>
    return <LoadError what="the storage" error={tree.error} onRetry={() => void tree.refetch()} />
  }
  const stale = <StaleNotice what="the storage" query={tree} />
  if (tree.data.length === 0)
    return <>{stale}<Typography>{canManage ? 'No storage yet. Start with a freezer or an LN2 tank.' : 'No storage yet. Curators and managers add freezers and tanks.'}</Typography></>
  return <>{stale}<StorageTree label={`Storage of ${labName}`} rows={tree.data} onOpen={onOpen} /></>
}
