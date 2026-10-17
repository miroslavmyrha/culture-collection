import { getRouteApi } from '@tanstack/react-router'
import { LabDetail } from '@/features/labs/components/LabDetail'

const route = getRouteApi('/_authenticated/labs/$labId')

export function LabDetailPage() {
  const { labId } = route.useParams()
  const search = route.useSearch()
  const navigate = route.useNavigate()
  return (
    <section>
      <LabDetail labId={labId} params={search} onOffsetChange={(offset) => void navigate({ search: (prev) => ({ ...prev, offset }) })} />
    </section>
  )
}
