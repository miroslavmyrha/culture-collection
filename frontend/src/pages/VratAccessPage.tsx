import { getRouteApi } from '@tanstack/react-router'
import { PageTitle, Typography } from '@/components/ui'
import { LabGate } from '@/features/labs/components/LabGate'
import { VratAccessSheet } from '@/features/labs/components/VratAccessSheet'
import { canManageMembers } from '@/features/labs/schemas'
import { VratPermitInForce } from '@/features/permits/components/VratPermitInForce'

const route = getRouteApi('/_authenticated/labs/$labId/vrat-access')

/** Thin: the lab's VRAT access list to print (#167), with its permit from the permits feature. */
export function VratAccessPage() {
  const { labId } = route.useParams()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`VRAT access list of ${lab.name}`}</PageTitle>
            {canManageMembers(lab.my_role) ? (
              <VratAccessSheet lab={lab} renderPermit={() => <VratPermitInForce labId={labId} />} />
            ) : (
              <>
                <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
                  VRAT access list of {lab.name}
                </Typography>
                <Typography>Only managers see the VRAT access list.</Typography>
              </>
            )}
          </>
        )}
      </LabGate>
    </section>
  )
}
