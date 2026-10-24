import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { Box, Container, Link } from '@/components/ui'
import { overviewOptions } from '@/features/home/api/queries'
import { useLab } from '@/features/labs/api/queries'
import { canSeeDeposits } from '@/features/labs/schemas'

/**
 * The tabs of a lab's sections under the top bar, on every page of the lab. Navigation links, not
 * ARIA tabs: each opens a page, so the router's aria-current="page" marks the active one (a
 * section stays active on its detail pages). On a narrow screen the row scrolls sideways inside
 * itself and the active tab is brought into view; the page does not (WCAG 1.4.10). Deposits,
 * Depositors and MTA templates show for curators and managers once the lab's role is known.
 *
 * Requests and Deposits carry how many wait for the person (#69): requests to decide, deposits
 * to check. The counts come from Home's one read of all the person's labs (one request for every
 * tab of every lab, refreshed by the writes that change them), and show only for a role that
 * acts on them and only when something waits.
 */
export function LabTabs({ labId }: { labId: string }) {
  const lab = useLab(labId)
  const figures = useQuery({ ...overviewOptions(), select: (overview) => overview.labs.find((entry) => entry.public_id === labId) }).data
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
          <Link to="/labs/$labId/requests" params={params} underline="none" sx={tabSx} aria-label={counted('Requests', figures?.requests_to_decide, 'to decide')}>
            Requests
            <TabCount count={figures?.requests_to_decide} />
          </Link>
          {canSeeDeposits(role) && (
            <>
              <Link to="/labs/$labId/deposits" params={params} underline="none" sx={tabSx} aria-label={counted('Deposits', figures?.deposits_to_check, 'to check')}>
                Deposits
                <TabCount count={figures?.deposits_to_check} />
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

/**
 * A count after a tab's name: a pill for the eye, and the link's name for a screen reader,
 * "Requests, 2 to decide", which starts with the visible name (WCAG 2.5.3). The name is a label,
 * not hidden text: browsers join inline parts of a name with spaces of their own.
 */
function TabCount({ count }: { count: number | null | undefined }) {
  if (!count) return null
  return (
    <Box component="span" aria-hidden sx={{ ml: 0.75, px: 0.75, minWidth: 20, borderRadius: '999px', bgcolor: 'action.selected', color: 'text.primary', fontSize: '0.75rem', fontWeight: 600, lineHeight: '20px', textAlign: 'center' }}>
      {count}
    </Box>
  )
}

const counted = (name: string, count: number | null | undefined, what: string) => (count ? `${name}, ${count} ${what}` : undefined)

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
