import { getRouteApi } from '@tanstack/react-router'
import { Link, PageTitle, Typography } from '@/components/ui'
import { NewRequestForm } from '@/features/distribution/components/NewRequestForm'
import { canManageRequests } from '@/features/distribution/schemas'
import { LabGate } from '@/features/labs/components/LabGate'

const route = getRouteApi('/_authenticated/labs/$labId/requests/new')

export function RequestNewPage() {
  const { labId } = route.useParams()
  const navigate = route.useNavigate()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`Enter a request in ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              Enter a request in {lab.name}
            </Typography>
            <Typography sx={{ mb: 3 }}>
              <Link to="/labs/$labId/requests" params={{ labId }}>
                Back to the requests
              </Link>
            </Typography>
            {canManageRequests(lab.my_role) ? (
              <NewRequestForm labId={labId} onSubmitted={(request) => void navigate({ to: '/labs/$labId/requests/$requestId', params: { labId, requestId: request.public_id } })} />
            ) : (
              <Typography>Only curators and managers enter requests. Your role lets you read them.</Typography>
            )}
          </>
        )}
      </LabGate>
    </section>
  )
}
