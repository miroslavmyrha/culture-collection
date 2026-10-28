import { getRouteApi } from '@tanstack/react-router'
import { Link, Typography } from '@/components/ui'
import { RequestDetail } from '@/features/distribution/components/RequestDetail'
import { LabGate } from '@/features/labs/components/LabGate'
import { VialsToPull } from '@/features/vials/components/VialsToPull'

const route = getRouteApi('/_authenticated/labs/$labId/requests/$requestId')

export function RequestDetailPage() {
  const { labId, requestId } = route.useParams()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <Typography sx={{ mb: 2 }}>
              <Link to="/labs/$labId/requests" params={{ labId }}>
                Requests of {lab.name}
              </Link>
            </Typography>
            <RequestDetail labId={labId} requestId={requestId} role={lab.my_role} renderVials={(request) => <VialsToPull labId={labId} requestId={request.public_id} />} />
          </>
        )}
      </LabGate>
    </section>
  )
}
