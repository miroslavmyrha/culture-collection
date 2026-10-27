import { getRouteApi } from '@tanstack/react-router'
import { PageTitle, Typography } from '@/components/ui'
import { MediaList } from '@/features/growth/components/MediaList'
import { LabGate } from '@/features/labs/components/LabGate'
import { canManageMedia } from '@/lib/roles'

const route = getRouteApi('/_authenticated/labs/$labId/media')

export function MediaListPage() {
  const { labId } = route.useParams()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`Media of ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              Media of {lab.name}
            </Typography>
            {canManageMedia(lab.my_role) ? (
              <>
                <Typography sx={{ mb: 2 }}>
                  The media the lab grows its strains on. A strain and each passage name one of them. A medium is never deleted: retire it, and it stays where
                  it was used.
                </Typography>
                <MediaList labId={labId} canManage />
              </>
            ) : (
              <Typography>Only curators and managers manage the media.</Typography>
            )}
          </>
        )}
      </LabGate>
    </section>
  )
}
