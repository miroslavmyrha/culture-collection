import { type ReactNode, useEffect, useRef } from 'react'
import { Box } from '@/components/ui'

/**
 * A row of tabs that are navigation links, not ARIA tabs: each opens its own URL, so the
 * router's aria-current="page" marks the active one. On a narrow screen the row scrolls sideways
 * inside itself and the active tab is brought into view; the page does not (WCAG 1.4.10). The
 * caller wraps it in a labelled nav and gives each link `tabSx`.
 */
export function TabRow({ children }: { children: ReactNode }) {
  const row = useRef<HTMLDivElement>(null)
  // jsdom has no scrollIntoView: a browser always does.
  const current = useRef<string | null>(null)
  useEffect(() => {
    const active = row.current?.querySelector<HTMLElement>('[aria-current="page"]')
    if (active && current.current !== active.textContent) active.scrollIntoView?.({ inline: 'center', block: 'nearest' })
    current.current = active?.textContent ?? null
  })
  return (
    <Box ref={row} sx={{ display: 'flex', gap: 0.5, overflowX: 'auto', scrollbarWidth: 'thin' }}>
      {children}
    </Box>
  )
}

export const tabSx = {
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
