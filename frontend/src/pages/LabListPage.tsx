import { getRouteApi } from '@tanstack/react-router'
import { Typography } from '@/components/ui'
import { LabList } from '@/features/labs/components/LabList'

const route = getRouteApi('/_authenticated/labs')

/** Thin: reads the URL state and composes the feature. The route file owns search and loader. */
export function LabListPage() {
  const search = route.useSearch()
  const navigate = route.useNavigate()
  return (
    <section>
      <Typography component="h1" variant="h4" gutterBottom>
        Labs
      </Typography>
      <LabList params={search} onOffsetChange={(offset) => void navigate({ search: (prev) => ({ ...prev, offset }) })} />
    </section>
  )
}
