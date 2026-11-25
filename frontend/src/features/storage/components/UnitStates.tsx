import type { useUnit } from '../api/queries'
import { DetailUnavailable } from '@/components/DetailUnavailable'

/** What the unit page shows while it has no unit: loading, not found, or the load error. */
export function UnitUnavailable({ unit }: { unit: ReturnType<typeof useUnit> }) {
  return <DetailUnavailable query={unit} noun="unit" notFound="The storage unit does not exist, or it is not in this lab." />
}
