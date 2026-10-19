import { LoadError } from '@/components/LoadError'
import { Typography } from '@/components/ui'
import { useUnitTree } from '../api/queries'
import { StorageTree } from './StorageTree'

type Props = { labId: string; labName: string; canManage: boolean; onOpen: (unitId: string) => void }

/** The lab's storage tree with its loading, error and empty states. */
export function UnitTree({ labId, labName, canManage, onOpen }: Props) {
  const tree = useUnitTree(labId)
  if (tree.isPending) return <Typography aria-busy>Loading the storage…</Typography>
  if (tree.isError) return <LoadError what="the storage" error={tree.error} onRetry={() => void tree.refetch()} />
  if (tree.data.length === 0)
    return <Typography>{canManage ? 'No storage yet. Start with a freezer or an LN2 tank.' : 'No storage yet. Curators and managers add freezers and tanks.'}</Typography>
  return <StorageTree label={`Storage of ${labName}`} rows={tree.data} onOpen={onOpen} />
}
