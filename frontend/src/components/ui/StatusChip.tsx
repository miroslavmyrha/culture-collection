import Box from '@mui/material/Box'
import type { ReactNode } from 'react'

/** What a status word means: colour only where it means something (success, warning, danger, info, regulated). */
export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'regulated' | 'neutral'

/**
 * A status as a small tinted label. The words carry the meaning, the tone only helps the eye, so
 * nothing relies on colour alone (WCAG 1.4.1). Text has 4.5:1 on its tint in both schemes
 * (src/app/theme.test.ts). With no tone it renders the words alone. Not interactive: no focus, no target size to meet.
 */
export function StatusChip({ tone, children }: { tone?: Tone; children: ReactNode }) {
  // No tone: the ordinary state (Active, Available) stays plain text, so colour marks only what needs a look.
  if (tone === undefined) return <>{children}</>
  return (
    <Box
      component="span"
      sx={(theme) => {
        const colors = (theme.vars ?? theme).palette.status[tone]
        return {
          display: 'inline-block',
          px: 0.75,
          py: '1px',
          border: `1px solid ${colors.border}`,
          borderRadius: '999px',
          bgcolor: colors.bg,
          color: colors.fg,
          fontSize: '0.75rem',
          fontWeight: 500,
          lineHeight: 1.5,
          whiteSpace: 'nowrap',
        }
      }}
    >
      {children}
    </Box>
  )
}
