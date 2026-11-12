import { LoadError } from '@/components/LoadError'
import { PageTitle, Typography } from '@/components/ui'
import { isApiError } from '@/lib/api'
import type { useUnit } from '../api/queries'

/** What the unit page shows while it has no unit: loading, not found, or the load error. */
export function UnitUnavailable({ unit }: { unit: ReturnType<typeof useUnit> }) {
  if (unit.isPending)
    return (
      <>
        <PageTitle>Loading the unit</PageTitle>
        <Typography>Loading the unit…</Typography>
      </>
    )
  // 404 means "not in this lab" as much as "does not exist": the text says both.
  if (isApiError(unit.error, 404))
    return (
      <>
        <PageTitle>Unit not found</PageTitle>
        <Typography component="h1" variant="h4" gutterBottom>
          Unit not found
        </Typography>
        <Typography>The storage unit does not exist, or it is not in this lab.</Typography>
      </>
    )
  return (
    <>
      <PageTitle>Could not load the unit</PageTitle>
      <LoadError what="the unit" error={unit.error} onRetry={() => void unit.refetch()} />
    </>
  )
}
