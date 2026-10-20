import { getRouteApi } from '@tanstack/react-router'
import { LabGate } from '@/features/labs/components/LabGate'
import { UnitDetail } from '@/features/storage/components/UnitDetail'
import { canManageStorage } from '@/features/storage/schemas'
import { BoxPositions } from '@/features/vials/components/BoxPositions'
import { canHandleVials } from '@/features/vials/schemas'

const route = getRouteApi('/_authenticated/labs/$labId/storage/$unitId')

export function StorageUnitPage() {
  const { labId, unitId } = route.useParams()
  const navigate = route.useNavigate()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <UnitDetail
            key={unitId}
            labId={labId}
            labName={lab.name}
            unitId={unitId}
            canManage={canManageStorage(lab.my_role)}
            onCreated={(unit) => void navigate({ to: '/labs/$labId/storage/$unitId', params: { labId, unitId: unit.public_id } })}
            renderContents={(unit) =>
              unit.kind === 'box' && (
                // A box out of service or retired takes no vial (may_store): its grid is read only.
                <BoxPositions labId={labId} boxId={unit.public_id} boxName={unit.name} canHandle={canHandleVials(lab.my_role) && unit.path_active} />
              )
            }
          />
        )}
      </LabGate>
    </section>
  )
}
