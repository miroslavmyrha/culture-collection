import { getRouteApi } from '@tanstack/react-router'
import { Link, PageTitle, Stack, Typography } from '@/components/ui'
import { RequesterList } from '@/features/distribution/components/RequesterList'
import { canManageRequests } from '@/features/distribution/schemas'
import { LabGate } from '@/features/labs/components/LabGate'

const route = getRouteApi('/_authenticated/labs/$labId/requesters')

export function RequesterListPage() {
  const { labId } = route.useParams()
  const search = route.useSearch()
  const navigate = route.useNavigate()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`Requesters of ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              Requesters of {lab.name}
            </Typography>
            <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', mb: 3 }}>
              <Link to="/labs/$labId/requests" params={{ labId }}>
                Back to the requests
              </Link>
            </Stack>
            {canManageRequests(lab.my_role) ? (
              <RequesterList
                labId={labId}
                params={search}
                canManage
                onOffsetChange={(offset) => void navigate({ search: (prev) => ({ ...prev, offset }) })}
                onSearch={(text) => void navigate({ search: (prev) => ({ ...prev, search: text, offset: 0 }) })}
              />
            ) : (
              <Typography>Only curators and managers see requesters: they name people.</Typography>
            )}
          </>
        )}
      </LabGate>
    </section>
  )
}
