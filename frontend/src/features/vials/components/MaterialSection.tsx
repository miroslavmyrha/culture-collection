import type { ReactNode } from 'react'
import { Box, Stack, Typography } from '@/components/ui'

/** One section of the Material tab: a heading focus can return to, and the section's content. */
export function MaterialSection({ title, children }: { title: string; children: ReactNode }) {
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
