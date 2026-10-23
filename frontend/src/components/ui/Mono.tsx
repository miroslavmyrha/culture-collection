import Box from '@mui/material/Box'
import type { ReactNode } from 'react'

/**
 * Accession numbers, vial labels, request numbers and hashes: one monospace style wherever they
 * are shown, so the eye finds them and a 0 is not an O. Digits do not shift (tabular), ligatures
 * are off, and a long hash breaks instead of widening the page (WCAG 1.4.10).
 */
export function Mono({ children }: { children: ReactNode }) {
  return (
    <Box
      component="span"
      sx={{
        fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
        fontSize: '1em',
        fontVariantLigatures: 'none',
        fontVariantNumeric: 'tabular-nums',
        overflowWrap: 'anywhere',
      }}
    >
      {children}
    </Box>
  )
}
