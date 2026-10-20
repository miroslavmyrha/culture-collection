import { getRouteApi } from '@tanstack/react-router'
import { Link, PageTitle, Stack, Typography } from '@/components/ui'
import { RequestFilters, RequestList } from '@/features/distribution/components/RequestList'
import { canManageRequests } from '@/features/distribution/schemas'
import { LabGate } from '@/features/labs/components/LabGate'

const route = getRouteApi('/_authenticated/labs/$labId/requests')

/** Thin: reads the URL state and composes the feature. The route file owns search and loader. */
export function RequestListPage() {
  const { labId } = route.useParams()
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const { limit, offset: _offset, ...filters } = search
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`Requests of ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              Requests of {lab.name}
            </Typography>
            <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', mb: 3 }}>
              <Link to="/labs/$labId" params={{ labId }}>
                Back to {lab.name}
              </Link>
              {canManageRequests(lab.my_role) && (
                <>
                  <Link to="/labs/$labId/requests/new" params={{ labId }}>
                    Enter a request
                  </Link>
                  <Link to="/labs/$labId/requesters" params={{ labId }}>
                    Requesters and their permits
                  </Link>
                </>
              )}
            </Stack>
            <RequestFilters filters={filters} onChange={(next) => void navigate({ search: { ...next, limit, offset: 0 } })} />
            <RequestList
              labId={labId}
              params={search}
              onOffsetChange={(offset) => void navigate({ search: (prev) => ({ ...prev, offset }) })}
              onClearFilters={() => void navigate({ search: { limit, offset: 0 } })}
            />
          </>
        )}
      </LabGate>
    </section>
  )
}
