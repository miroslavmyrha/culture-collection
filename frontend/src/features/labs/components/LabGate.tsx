import type { ReactNode } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { PageTitle, Typography } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { useLab } from '../api/queries'
import type { Lab } from '../schemas'

type Props = { labId: string; children: (lab: Lab) => ReactNode }

/**
 * A page inside a lab (its strains, later its storage): loads the lab and renders the page
 * with it, or the lab's own loading, not found and error states, each with its title. Once
 * the lab loaded, a failed refresh keeps the page (and every form and dialog on it) with a
 * stale notice: the states replace the page only while there is no lab to show.
 */
export function LabGate({ labId, children }: Props) {
  const lab = useLab(labId)
  if (lab.data === undefined) {
    if (lab.isPending)
      return (
        <>
          <PageTitle>Loading the lab</PageTitle>
          <Typography>Loading the lab…</Typography>
        </>
      )
    // 404 means "not a member" as much as "does not exist": the text says both.
    if (isApiError(lab.error, 404))
      return (
        <>
          <PageTitle>Lab not found</PageTitle>
          <Typography component="h1" variant="h4" gutterBottom>
            Lab not found
          </Typography>
          <Typography>The lab does not exist, or you are not a member of it.</Typography>
        </>
      )
    return (
      <>
        <PageTitle>Could not load the lab</PageTitle>
        <LoadError what="the lab" error={lab.error} onRetry={() => void lab.refetch()} />
      </>
    )
  }
  return (
    <>
      <StaleNotice what="the lab" query={lab} />
      {children(lab.data)}
    </>
  )
}
