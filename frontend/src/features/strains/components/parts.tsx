import type { ReactNode } from 'react'
import { Paper } from '@/components/ui'
import { day } from '@/lib/dates'
import { Facts, Section as DetailSection } from '@/components/DetailParts'

// The parts every tab of the strain page is built from.

/** The local calendar day of a time, as YYYY-MM-DD (the identification dates are local days too). */

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

/** The strain page's sections stack from the top, with the space below. */
export function Section(props: { title: string; children: ReactNode }) {
  return <DetailSection {...props} space="below" />
}

export { day, Facts }
