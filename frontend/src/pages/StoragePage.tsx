import { getRouteApi } from '@tanstack/react-router'
import { type MouseEvent, useRef, useState } from 'react'
import { Button, Link, PageTitle, Stack, Typography } from '@/components/ui'
import { LabGate } from '@/features/labs/components/LabGate'
import { CreateUnitDialog } from '@/features/storage/components/UnitDialogs'
import { UnitTree } from '@/features/storage/components/UnitTree'
import { canManageStorage } from '@/features/storage/schemas'
import { type FocusReturn, rememberFocus } from '@/lib/focus'

const route = getRouteApi('/_authenticated/labs/$labId/storage')

/** Thin: the lab, its storage tree, and for curators the way to add a freezer or tank. */
export function StoragePage() {
  const { labId } = route.useParams()
  const navigate = route.useNavigate()
  const [adding, setAdding] = useState<boolean | null>(null)
  const spot = useRef<FocusReturn | null>(null)
  const open = (unitId: string) => void navigate({ to: '/labs/$labId/storage/$unitId', params: { labId, unitId } })
  const start = (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    setAdding(true)
  }
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`Storage of ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              Storage of {lab.name}
            </Typography>
            <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', alignItems: 'center', mb: 3 }}>
              <Link to="/labs/$labId" params={{ labId }}>
                Back to {lab.name}
              </Link>
              {canManageStorage(lab.my_role) && (
                <Button variant="contained" onClick={start}>
                  Add a freezer or tank
                </Button>
              )}
            </Stack>
            <UnitTree labId={labId} labName={lab.name} canManage={canManageStorage(lab.my_role)} onOpen={open} />
            {/* Mounted until it has faded out, so onExited can place the focus. */}
            {adding !== null && (
              <CreateUnitDialog
                labId={labId}
                parent={null}
                open={adding}
                onClose={() => setAdding(false)}
                onExited={() => {
                  spot.current?.restore()
                  setAdding(null)
                }}
                onCreated={(unit) => open(unit.public_id)}
              />
            )}
          </>
        )}
      </LabGate>
    </section>
  )
}
