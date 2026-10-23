import { useEffect, useRef } from 'react'
import { Box, Container, Link } from '@/components/ui'
import { useLab } from '@/features/labs/api/queries'
import { canSeeDeposits } from '@/features/labs/schemas'

/**
 * The tabs of a lab's sections under the top bar, on every page of the lab. Navigation links, not
 * ARIA tabs: each opens a page, so the router's aria-current="page" marks the active one (a
 * section stays active on its detail pages). On a narrow screen the row scrolls sideways inside
 * itself and the active tab is brought into view; the page does not (WCAG 1.4.10). Deposits,
 * Depositors and MTA templates show for curators and managers once the lab's role is known.
 */
export function LabTabs({ labId }: { labId: string }) {
  const lab = useLab(labId)
  const row = useRef<HTMLDivElement>(null)
  const role = lab.data?.my_role
  // A lab the user cannot open (404) or that failed to load has no sections to show.
  const hidden = lab.data === undefined && !lab.isPending

  // jsdom has no scrollIntoView: a browser always does.
  const current = useRef<string | null>(null)
  useEffect(() => {
    const active = row.current?.querySelector<HTMLElement>('[aria-current="page"]')
    if (active && current.current !== active.textContent) active.scrollIntoView?.({ inline: 'center', block: 'nearest' })
    current.current = active?.textContent ?? null
  })

  if (hidden) return null
  const params = { labId }
  return (
    <Box component="nav" aria-label="Lab sections" sx={{ bgcolor: 'background.paper', borderBottom: 1, borderColor: 'divider', displayPrint: 'none' }}>
      <Container maxWidth="lg" sx={{ px: { xs: 1, sm: 2 } }}>
        <Box ref={row} sx={{ display: 'flex', gap: 0.5, overflowX: 'auto', scrollbarWidth: 'thin' }}>
          <Link to="/labs/$labId/strains" params={params} underline="none" sx={tabSx}>
            Strains
          </Link>
          <Link to="/labs/$labId/storage" params={params} underline="none" sx={tabSx}>
            Storage
          </Link>
          <Link to="/labs/$labId/requests" params={params} underline="none" sx={tabSx}>
            Requests
          </Link>
          {canSeeDeposits(role) && (
            <>
              <Link to="/labs/$labId/deposits" params={params} underline="none" sx={tabSx}>
                Deposits
              </Link>
              <Link to="/labs/$labId/depositors" params={params} underline="none" sx={tabSx}>
                Depositors
              </Link>
              <Link to="/labs/$labId/mta-templates" params={params} underline="none" sx={tabSx}>
                MTA templates
              </Link>
            </>
          )}
        </Box>
      </Container>
    </Box>
  )
}

const tabSx = {
  display: 'flex',
  alignItems: 'center',
  flexShrink: 0,
  minHeight: 40,
  px: 1.5,
  color: 'text.secondary',
  whiteSpace: 'nowrap',
  borderBottom: '2px solid transparent',
  '&:hover': { color: 'text.primary', bgcolor: 'action.hover' },
  // The ring sits inside the tab: the row scrolls, and a ring outside it would be clipped.
  '&.Mui-focusVisible': { outlineOffset: -2 },
  '&[aria-current="page"]': { color: 'text.primary', fontWeight: 600, borderBottomColor: 'primary.main' },
} as const
