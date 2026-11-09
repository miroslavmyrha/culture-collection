import { getRouteApi } from '@tanstack/react-router'
import { PageTitle, Typography } from '@/components/ui'
import { LabGate } from '@/features/labs/components/LabGate'
import { ListDisagreements } from '@/features/strains/components/ListDisagreements'
import { canSeeListDisagreements } from '@/lib/roles'

const route = getRouteApi('/_authenticated/labs/$labId/classification')

const INTRO =
  'Where the lab’s record and the official lists disagree: an entry names a restriction a strain does not carry, a strain carries one no entry names, or an entry of annex 7 of 361/2007 Sb. states another risk group. Checked at every read, so it follows every reclassification and every new reading of a list. Nothing here decides anything: a strain’s taxon may be wrong, an annex may name a genus where the lab holds a species, and an agent annex 7 does not list is not thereby group 1. Settle one on the strain’s own page, with a reason.'

/** Thin: reads the URL state and composes the feature. The route file owns search and loader. */
export function ClassificationPage() {
  const { labId } = route.useParams()
  const search = route.useSearch()
  const navigate = route.useNavigate()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`Classification of ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              Classification of {lab.name}
            </Typography>
            {canSeeListDisagreements(lab.my_role) ? (
              <>
                <Typography sx={{ mb: 2 }}>{INTRO}</Typography>
                <ListDisagreements labId={labId} params={search} onOffsetChange={(offset) => void navigate({ search: (prev) => ({ ...prev, offset }) })} />
              </>
            ) : (
              <Typography>Only managers see where the classification disagrees with the official lists.</Typography>
            )}
          </>
        )}
      </LabGate>
    </section>
  )
}
