import { getRouteApi } from '@tanstack/react-router'
import { Link, PageTitle, Stack, Typography } from '@/components/ui'
import { DepositFilters, DepositList } from '@/features/deposits/components/DepositList'
import { canHandleDeposits } from '@/features/deposits/schemas'
import { LabGate } from '@/features/labs/components/LabGate'

const route = getRouteApi('/_authenticated/labs/$labId/deposits')

/** Thin: reads the URL state and composes the feature. The route file owns search and loader. */
export function DepositListPage() {
  const { labId } = route.useParams()
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const { limit, offset: _offset, ...filters } = search
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`Deposits of ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              Deposits of {lab.name}
            </Typography>
            <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', mb: 3 }}>
              <Link to="/labs/$labId" params={{ labId }}>
                Back to {lab.name}
              </Link>
              {canHandleDeposits(lab.my_role) && (
                <Link to="/labs/$labId/deposits/new" params={{ labId }}>
                  Receive a deposit
                </Link>
              )}
            </Stack>
            {canHandleDeposits(lab.my_role) ? (
              <>
                <DepositFilters filters={filters} onChange={(next) => void navigate({ search: { ...next, limit, offset: 0 } })} />
                <DepositList
                  labId={labId}
                  params={search}
                  onOffsetChange={(offset) => void navigate({ search: (prev) => ({ ...prev, offset }) })}
                  onClearFilters={() => void navigate({ search: { limit, offset: 0 } })}
                />
              </>
            ) : (
              <Typography>Only curators and managers see deposits: they name their depositors.</Typography>
            )}
          </>
        )}
      </LabGate>
    </section>
  )
}
