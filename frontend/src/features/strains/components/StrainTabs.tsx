import { TabRow, tabSx } from '@/components/TabRow'
import { Box, Link } from '@/components/ui'

/**
 * The strain page by task (#19): what the strain is, its material, its terms of use and what
 * happened to it, each tab its own URL that loads only its own data. Links, not ARIA tabs (the
 * lab's tabs explain why); Overview is active only on its own URL.
 */
export function StrainTabs({ labId, strainId }: { labId: string; strainId: string }) {
  const params = { labId, strainId }
  return (
    <Box component="nav" aria-label="Strain sections" sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
      <TabRow>
        <Link to="/labs/$labId/strains/$strainId" params={params} activeOptions={{ exact: true, includeSearch: false }} underline="none" sx={tabSx}>
          Overview
        </Link>
        <Link to="/labs/$labId/strains/$strainId/material" params={params} activeOptions={{ includeSearch: false }} underline="none" sx={tabSx}>
          Material
        </Link>
        <Link to="/labs/$labId/strains/$strainId/terms" params={params} underline="none" sx={tabSx}>
          Terms
        </Link>
        <Link to="/labs/$labId/strains/$strainId/history" params={params} activeOptions={{ includeSearch: false }} underline="none" sx={tabSx}>
          History
        </Link>
      </TabRow>
    </Box>
  )
}
