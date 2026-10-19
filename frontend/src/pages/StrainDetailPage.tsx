import { getRouteApi } from '@tanstack/react-router'
import { Link, Typography } from '@/components/ui'
import { LabGate } from '@/features/labs/components/LabGate'
import { StrainDetail } from '@/features/strains/components/StrainDetail'
import { canManageStrains } from '@/features/strains/schemas'
import { StrainMaterial } from '@/features/vials/components/StrainMaterial'
import { canHandleVials } from '@/features/vials/schemas'

const route = getRouteApi('/_authenticated/labs/$labId/strains/$strainId')

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
            <StrainDetail
              labId={labId}
              strainId={strainId}
              canManage={canManageStrains(lab.my_role)}
              renderMaterial={(strain) => (
                <StrainMaterial
                  labId={labId}
                  strainId={strain.public_id}
                  accession={strain.accession_number ?? 'the strain'}
                  canHandle={canHandleVials(lab.my_role)}
                />
              )}
            />
          </>
        )}
      </LabGate>
    </section>
  )
}
