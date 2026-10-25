import { useQuery } from '@tanstack/react-query'
import { TabRow, tabSx } from '@/components/TabRow'
import { Box, Container, Link } from '@/components/ui'
import { overviewOptions } from '@/features/home/api/queries'
import { useLab } from '@/features/labs/api/queries'
import { canHandleDeposits } from '@/lib/roles'

/**
 * The tabs of a lab's sections under the top bar, on every page of the lab. Navigation links, not
 * ARIA tabs: each opens a page, so the router's aria-current="page" marks the active one (a
 * section stays active on its detail pages). On a narrow screen the row scrolls sideways inside
 * itself and the active tab is brought into view; the page does not (WCAG 1.4.10). Deposits,
 * Depositors and MTA templates show for curators and managers once the lab's role is known.
 * The row and the tab style are shared with the strain page's tabs (components/TabRow).
 *
 * Requests and Deposits carry how many wait for the person (#69): requests to decide, deposits
 * to check. The counts come from Home's one read of all the person's labs (one request for every
 * tab of every lab, refreshed by the writes that change them), and show only for a role that
 * acts on them and only when something waits.
 */
export function LabTabs({ labId }: { labId: string }) {
  const lab = useLab(labId)
  const figures = useQuery({ ...overviewOptions(), select: (overview) => overview.labs.find((entry) => entry.public_id === labId) }).data
  const role = lab.data?.my_role
  // A lab the user cannot open (404) or that failed to load has no sections to show.
  const hidden = lab.data === undefined && !lab.isPending

  if (hidden) return null
  const params = { labId }
  return (
    <Box component="nav" aria-label="Lab sections" sx={{ bgcolor: 'background.paper', borderBottom: 1, borderColor: 'divider', displayPrint: 'none' }}>
      <Container maxWidth="lg" sx={{ px: { xs: 1, sm: 2 } }}>
        <TabRow>
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
          {canHandleDeposits(role) && (
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
        </TabRow>
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
