import { getRouteApi } from '@tanstack/react-router'
import { Link, PageTitle, Typography } from '@/components/ui'
import { MtaTemplateDetail } from '@/features/deposits/components/MtaTemplateDetail'
import { canHandleDeposits, canPublishMta } from '@/features/deposits/schemas'
import { LabGate } from '@/features/labs/components/LabGate'

const route = getRouteApi('/_authenticated/labs/$labId/mta-templates/$templateId')

export function MtaTemplateDetailPage() {
  const { labId, templateId } = route.useParams()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <Typography sx={{ mb: 2 }}>
              <Link to="/labs/$labId/mta-templates" params={{ labId }}>
                MTA templates of {lab.name}
              </Link>
            </Typography>
            {canHandleDeposits(lab.my_role) ? (
              <MtaTemplateDetail labId={labId} templateId={templateId} canPublish={canPublishMta(lab.my_role)} />
            ) : (
              <>
                <PageTitle>MTA template</PageTitle>
                <Typography>Only curators and managers see the MTA templates.</Typography>
              </>
            )}
          </>
        )}
      </LabGate>
    </section>
  )
}
