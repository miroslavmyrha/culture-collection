import { getRouteApi, Outlet } from '@tanstack/react-router'
import { Link, PageTitle, Typography } from '@/components/ui'
import { useLab } from '@/features/labs/api/queries'
import { LabGate } from '@/features/labs/components/LabGate'
import { useStrain } from '@/features/strains/api/queries'
import { StrainHistory } from '@/features/strains/components/StrainHistory'
import { StrainOverview } from '@/features/strains/components/StrainOverview'
import { StrainShell } from '@/features/strains/components/StrainShell'
import { StrainTabs } from '@/features/strains/components/StrainTabs'
import { StrainTerms } from '@/features/strains/components/StrainTerms'
import { canConfirmDeaccession, canConfirmRestrictionEnd, canManageStrains } from '@/features/strains/schemas'
import { StrainMaterial } from '@/features/vials/components/StrainMaterial'
import { canHandleVials, canReleaseBatches } from '@/features/vials/schemas'

const route = getRouteApi('/_authenticated/labs/$labId/strains/$strainId')
const historyRoute = getRouteApi('/_authenticated/labs/$labId/strains/$strainId/history')
const materialRoute = getRouteApi('/_authenticated/labs/$labId/strains/$strainId/material')

/** The strain's page around its tabs (#19): the lab, the strain's header and the tab links. */
export function StrainDetailPage() {
  const { labId, strainId } = route.useParams()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <Typography sx={{ mb: 2 }}>
              <Link to="/labs/$labId/strains" params={{ labId }}>
                Strains of {lab.name}
              </Link>
            </Typography>
            <StrainShell labId={labId} strainId={strainId} canManage={canManageStrains(lab.my_role)}>
              {() => (
                <>
                  <StrainTabs labId={labId} strainId={strainId} />
                  <Outlet />
                </>
              )}
            </StrainShell>
          </>
        )}
      </LabGate>
    </section>
  )
}

/**
 * What a tab needs from the page around it: the lab's role and the strain, both loaded before
 * the tab renders (LabGate and StrainShell), so the tab only reads the cache.
 */
function useTab() {
  const { labId, strainId } = route.useParams()
  const lab = useLab(labId).data
  const strain = useStrain(labId, strainId).data
  return { labId, strainId, role: lab?.my_role, strain, number: strain?.accession_number ?? 'Pending strain' }
}

export function StrainOverviewPage() {
  const { labId, role, strain, number } = useTab()
  if (strain === undefined) return null
  return (
    <>
      <PageTitle>{number}</PageTitle>
      <StrainOverview
        labId={labId}
        strain={strain}
        canManage={canManageStrains(role)}
        canConfirm={canConfirmRestrictionEnd(role)}
        canConfirmLeave={canConfirmDeaccession(role)}
      />
    </>
  )
}

export function StrainMaterialPage() {
  const { labId, strainId, role, strain, number } = useTab()
  const page = materialRoute.useSearch()
  const navigate = materialRoute.useNavigate()
  return (
    <>
      <PageTitle>{`${number}, material`}</PageTitle>
      <StrainMaterial
        labId={labId}
        strainId={strainId}
        accession={strain?.accession_number ?? 'the strain'}
        strainGrowth={strain?.growth}
        canHandle={canHandleVials(role)}
        canRelease={canReleaseBatches(role)}
        vialPage={page}
        onVialPage={(next) => void navigate({ search: (prev) => ({ ...prev, ...next }) })}
      />
    </>
  )
}

export function StrainTermsPage() {
  const { labId, strainId, number } = useTab()
  return (
    <>
      <PageTitle>{`${number}, terms`}</PageTitle>
      <StrainTerms labId={labId} strainId={strainId} />
    </>
  )
}

export function StrainHistoryPage() {
  const { labId, strainId, number } = useTab()
  const page = historyRoute.useSearch()
  const navigate = historyRoute.useNavigate()
  return (
    <>
      <PageTitle>{`${number}, history`}</PageTitle>
      <StrainHistory labId={labId} strainId={strainId} page={page} onOffsetChange={(offset) => void navigate({ search: (prev) => ({ ...prev, offset }) })} />
    </>
  )
}
