import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Typography } from '@/components/ui'
import { useOverview } from '../api/queries'
import { MyLabs } from './MyLabs'
import { QuickActions } from './QuickActions'
import { RecentActivity } from './RecentActivity'
import { Waiting } from './Waiting'

/**
 * Home (#69), in the owner's order: what waits for the person, their labs, the recent activity
 * and the actions their roles start. The first, second and fourth come from one read; the
 * activity has its own, so a failure of one leaves the other on screen.
 */
export function Home() {
  const overview = useOverview()
  if (overview.data === undefined) {
    return (
      <>
        {overview.isPending ? (
          <Typography sx={{ mb: 4 }}>Loading what waits for you…</Typography>
        ) : (
          <LoadError what="what waits for you" error={overview.error} onRetry={() => void overview.refetch()} />
        )}
        <RecentActivity />
      </>
    )
  }
  const { waiting, labs } = overview.data
  return (
    <>
      <StaleNotice what="what waits for you" query={overview} />
      <Waiting groups={waiting} labs={labs} />
      <MyLabs labs={labs} />
      <RecentActivity />
      <QuickActions labs={labs} />
    </>
  )
}
