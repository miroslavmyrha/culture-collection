import { getRouteApi } from '@tanstack/react-router'
import { PageTitle, Typography } from '@/components/ui'
import { LabGate } from '@/features/labs/components/LabGate'
import { RevealFilters, RevealLog } from '@/features/reveals/components/RevealLog'
import { canSeeReveals } from '@/lib/roles'

const route = getRouteApi('/_authenticated/labs/$labId/reveals')

/** Thin: reads the URL state and composes the feature. The route file owns search and loader. */
export function RevealListPage() {
  const { labId } = route.useParams()
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const { limit, offset: _offset, ...filters } = search
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`Reveals of ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              Reveals of {lab.name}
            </Typography>
            {canSeeReveals(lab.my_role) ? (
              <>
                <Typography sx={{ mb: 2 }}>
                  Who revealed where a vial of a regulated strain is stored, which vial and when. Each reveal is recorded before the place is shown. The place
                  itself is never recorded, so it is not here either.
                </Typography>
                <RevealFilters
                  filters={filters}
                  onChange={(update) =>
                    void navigate({
                      search: (prev) => {
                        const { limit: keep, offset: _dropped, ...current } = prev
                        return { ...update(current), limit: keep, offset: 0 }
                      },
                    })
                  }
                />
                <RevealLog
                  labId={labId}
                  params={search}
                  onOffsetChange={(offset) => void navigate({ search: (prev) => ({ ...prev, offset }) })}
                  onPerson={(person) => void navigate({ search: (prev) => ({ ...prev, person, offset: 0 }) })}
                  onClearFilters={() => void navigate({ search: { limit, offset: 0 } })}
                />
              </>
            ) : (
              <Typography>Only managers see who revealed regulated locations.</Typography>
            )}
          </>
        )}
      </LabGate>
    </section>
  )
}
