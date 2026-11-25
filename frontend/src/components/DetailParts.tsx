import type { ReactNode } from 'react'
import { Box, Stack, Typography } from '@/components/ui'

type SectionProps = { title: string; children: ReactNode; space?: 'above' | 'below' }

/**
 * A titled part of a detail screen (#67). Its heading is where focus goes when the control that
 * had it is gone. `space` keeps each screen's rhythm: below where sections stack from the top.
 */
export function Section({ title, children, space = 'above' }: SectionProps) {
  return (
    <Box component="section" aria-label={title} sx={space === 'above' ? { mt: 4 } : { mb: 4 }}>
      {/* tabIndex -1: where focus goes when the control that had it is gone. */}
      <Typography component="h2" variant="h6" tabIndex={-1} gutterBottom>
        {title}
      </Typography>
      <Stack spacing={2}>{children}</Stack>
    </Box>
  )
}

/** Label and value pairs as a description list: two columns from small screens up. */
export function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <Box component="dl" sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'max-content 1fr' }, columnGap: 3, rowGap: 1, m: 0 }}>
      {rows.map(([label, value]) => (
        <Box key={label} sx={{ display: 'contents' }}>
          <Typography component="dt" sx={{ fontWeight: 'bold' }}>
            {label}
          </Typography>
          <Typography component="dd" sx={{ m: 0, overflowWrap: 'anywhere' }}>
            {value}
          </Typography>
        </Box>
      ))}
    </Box>
  )
}
