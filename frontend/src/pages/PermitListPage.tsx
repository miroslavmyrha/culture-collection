import { getRouteApi } from '@tanstack/react-router'
import { PageTitle, Typography } from '@/components/ui'
import { LabGate } from '@/features/labs/components/LabGate'
import { PermitList } from '@/features/permits/components/PermitList'
import { canSeePermits } from '@/lib/roles'

const route = getRouteApi('/_authenticated/labs/$labId/permits')

export function PermitListPage() {
  const { labId } = route.useParams()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`Permits of ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              Permits of {lab.name}
            </Typography>
            {canSeePermits(lab.my_role) ? (
              <>
                <Typography sx={{ mb: 2 }}>
                  The permits the lab holds for regulated strains, and when each one stops being valid. A strain with such a restriction is accepted only while
                  the lab holds a valid permit of its kind. This list is read only: staff record a permit and its end in the Django admin.
                </Typography>
                <PermitList labId={labId} />
              </>
            ) : (
              <Typography>Only managers see the lab&apos;s permits.</Typography>
            )}
          </>
        )}
      </LabGate>
    </section>
  )
}
