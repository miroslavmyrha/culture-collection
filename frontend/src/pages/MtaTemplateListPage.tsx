import { getRouteApi } from '@tanstack/react-router'
import { Link, PageTitle, Stack, Typography } from '@/components/ui'
import { MtaTemplateList } from '@/features/deposits/components/MtaTemplateList'
import { canHandleDeposits, canPublishMta } from '@/features/deposits/schemas'
import { LabGate } from '@/features/labs/components/LabGate'

const route = getRouteApi('/_authenticated/labs/$labId/mta-templates')

export function MtaTemplateListPage() {
  const { labId } = route.useParams()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`MTA templates of ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              MTA templates of {lab.name}
            </Typography>
            {canPublishMta(lab.my_role) && (
              <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', mb: 3 }}>
                <Link to="/labs/$labId/mta-templates/new" params={{ labId }}>
                  Publish an MTA version
                </Link>
              </Stack>
            )}
            {canHandleDeposits(lab.my_role) ? (
              <MtaTemplateList labId={labId} />
            ) : (
              <Typography>Only curators and managers see the MTA templates.</Typography>
            )}
          </>
        )}
      </LabGate>
    </section>
  )
}
