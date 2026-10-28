import { Paper } from '@/components/ui'

/**
 * A table that may be wider than the screen: a focusable named region in a frame, so a
 * keyboard user can scroll it (WCAG 2.1.1; axe scrollable-region-focusable).
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
