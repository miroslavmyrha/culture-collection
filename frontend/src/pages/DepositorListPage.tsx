import { getRouteApi } from '@tanstack/react-router'
import { PageTitle, Typography } from '@/components/ui'
import { DepositorList } from '@/features/deposits/components/DepositorList'
import { canHandleDeposits } from '@/features/deposits/schemas'
import { LabGate } from '@/features/labs/components/LabGate'

const route = getRouteApi('/_authenticated/labs/$labId/depositors')

export function DepositorListPage() {
  const { labId } = route.useParams()
  const search = route.useSearch()
  const navigate = route.useNavigate()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`Depositors of ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              Depositors of {lab.name}
            </Typography>
            {canHandleDeposits(lab.my_role) ? (
              <DepositorList
                labId={labId}
                params={search}
                onOffsetChange={(offset) => void navigate({ search: (prev) => ({ ...prev, offset }) })}
                onSearch={(text) => void navigate({ search: (prev) => ({ ...prev, search: text, offset: 0 }) })}
              />
            ) : (
              <Typography>Only curators and managers see depositors: their contacts are personal data.</Typography>
            )}
          </>
        )}
      </LabGate>
    </section>
  )
}
