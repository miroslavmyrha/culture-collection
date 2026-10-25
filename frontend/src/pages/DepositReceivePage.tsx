import { getRouteApi } from '@tanstack/react-router'
import { Link, PageTitle, Typography } from '@/components/ui'
import { ReceiveDepositForm } from '@/features/deposits/components/ReceiveDepositForm'
import { canHandleDeposits } from '@/lib/roles'
import { LabGate } from '@/features/labs/components/LabGate'

const route = getRouteApi('/_authenticated/labs/$labId/deposits/new')

export function DepositReceivePage() {
  const { labId } = route.useParams()
  const navigate = route.useNavigate()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`Receive a deposit in ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              Receive a deposit in {lab.name}
            </Typography>
            <Typography sx={{ mb: 3 }}>
              <Link to="/labs/$labId/deposits" params={{ labId }}>
                Back to the deposits
              </Link>
            </Typography>
            {canHandleDeposits(lab.my_role) ? (
              <ReceiveDepositForm
                labId={labId}
                onReceived={(deposit) => void navigate({ to: '/labs/$labId/deposits/$depositId', params: { labId, depositId: deposit.public_id } })}
              />
            ) : (
              <Typography>Only curators and managers receive deposits. Your role in this lab lets you read the strains.</Typography>
            )}
          </>
        )}
      </LabGate>
    </section>
  )
}
