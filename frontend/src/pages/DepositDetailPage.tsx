import { getRouteApi } from '@tanstack/react-router'
import { Link, PageTitle, Typography } from '@/components/ui'
import { useAcceptDeposit } from '@/features/deposits/api/mutations'
import { DepositDetail } from '@/features/deposits/components/DepositDetail'
import type { Deposit } from '@/features/deposits/schemas'
import { canHandleDeposits } from '@/lib/roles'
import { LabGate } from '@/features/labs/components/LabGate'
import { StrainFactsForm } from '@/features/strains/components/StrainFactsForm'
import { isCountry } from '@/lib/countries'

const route = getRouteApi('/_authenticated/labs/$labId/deposits/$depositId')

/** Composes the deposit (deposits) with the facts of the strain its acceptance creates (strains). */
export function DepositDetailPage() {
  const { labId, depositId } = route.useParams()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <Typography sx={{ mb: 2 }}>
              <Link to="/labs/$labId/deposits" params={{ labId }}>
                Deposits of {lab.name}
              </Link>
            </Typography>
            {canHandleDeposits(lab.my_role) ? (
              <DepositDetail labId={labId} depositId={depositId} canManage renderAccept={(deposit) => <AcceptStep labId={labId} deposit={deposit} />} />
            ) : (
              <>
                <PageTitle>Deposit</PageTitle>
                <Typography>Only curators and managers see deposits: they name their depositors.</Typography>
              </>
            )}
          </>
        )}
      </LabGate>
    </section>
  )
}

function AcceptStep({ labId, deposit }: { labId: string; deposit: Deposit }) {
  const accept = useAcceptDeposit(labId, deposit.public_id)
  const country = deposit.terms.country_of_origin
  return (
    <StrainFactsForm
      label="Accept the deposit"
      submitLabel="Accept and add the strain"
      nameAsReceived={deposit.name_as_received}
      country={isCountry(country) ? country : ''}
      // The mutation also refreshes the lab's strain lists, which show the new strain.
      submit={accept}
    />
  )
}
