import { getRouteApi } from '@tanstack/react-router'
import { LabGate } from '@/features/labs/components/LabGate'
import { UnitDetail } from '@/features/storage/components/UnitDetail'
import { canManageStorage } from '@/features/storage/schemas'

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
          />
        )}
      </LabGate>
    </section>
  )
}
