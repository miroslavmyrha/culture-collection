import type { ReactNode } from 'react'
import { Box, Paper, Stack, Typography } from '@/components/ui'

// The parts every tab of the strain page is built from.

/** The local calendar day of a time, as YYYY-MM-DD (the identification dates are local days too). */
export const day = (iso: string) => new Date(iso).toLocaleDateString('sv')

/**
 * A table that may scroll sideways on a narrow screen. Its container is a named region and a
 * tab stop, so a keyboard user can scroll it with the arrow keys also when no cell holds a
 * control (WCAG 2.1.1; axe scrollable-region-focusable).
 */
export const scrollable = (name: string) =>
  ({
    component: Paper,
    variant: 'outlined',
    tabIndex: 0,
    role: 'region',
    'aria-label': `${name} table`,
    sx: { '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 2 } },
  }) as const

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Box component="section" aria-label={title} sx={{ mb: 4 }}>
      {/* tabIndex -1: where focus goes when the control that had it is gone. */}
      <Typography component="h2" variant="h6" tabIndex={-1} gutterBottom>
        {title}
      </Typography>
      <Stack spacing={2}>{children}</Stack>
    </Box>
  )
}

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
