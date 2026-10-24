import { getRouteApi } from '@tanstack/react-router'
import { Link, PageTitle, Stack, Typography } from '@/components/ui'
import { LabGate } from '@/features/labs/components/LabGate'
import { canSeeDeposits } from '@/features/labs/schemas'
import { StrainFilters } from '@/features/strains/components/StrainFilters'
import { StrainList } from '@/features/strains/components/StrainList'

const route = getRouteApi('/_authenticated/labs/$labId/strains')

/** Thin: reads the URL state and composes the features. The route file owns search and loader. */
export function StrainListPage() {
  const { labId } = route.useParams()
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const { limit, offset: _offset, ...filters } = search
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`Strains of ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              Strains of {lab.name}
            </Typography>
            {/* A strain comes from an accepted deposit (ADR 0008, amendment of 2026-10-19). */}
            {canSeeDeposits(lab.my_role) && (
              <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', alignItems: 'center', mb: 3 }}>
                <Link to="/labs/$labId/deposits/new" params={{ labId }}>
                  Receive a deposit
                </Link>
              </Stack>
            )}
            <StrainFilters
              filters={filters}
              onChange={(update) => void navigate({ search: (prev) => { const { limit: keep, offset: _dropped, ...current } = prev; return { ...update(current), limit: keep, offset: 0 } } })}
            />
            <StrainList
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
