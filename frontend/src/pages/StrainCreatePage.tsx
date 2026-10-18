import { getRouteApi } from '@tanstack/react-router'
import { Link, PageTitle, Typography } from '@/components/ui'
import { LabGate } from '@/features/labs/components/LabGate'
import { CreateStrainForm } from '@/features/strains/components/CreateStrainForm'
import { canManageStrains } from '@/features/strains/schemas'

const route = getRouteApi('/_authenticated/labs/$labId/strains/new')

export function StrainCreatePage() {
  const { labId } = route.useParams()
  const navigate = route.useNavigate()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`Add a strain to ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              Add a strain to {lab.name}
            </Typography>
            <Typography sx={{ mb: 3 }}>
              <Link to="/labs/$labId/strains" params={{ labId }}>
                Back to the strains
              </Link>
            </Typography>
            {canManageStrains(lab.my_role) ? (
              <CreateStrainForm
                labId={labId}
                onCreated={(strain) => void navigate({ to: '/labs/$labId/strains/$strainId', params: { labId, strainId: strain.public_id } })}
              />
            ) : (
              <Typography>Only curators and managers add strains. Your role in this lab lets you read them.</Typography>
            )}
          </>
        )}
      </LabGate>
    </section>
  )
}
