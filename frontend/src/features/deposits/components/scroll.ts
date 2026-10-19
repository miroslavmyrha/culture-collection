/** A table that may scroll sideways and holds no control: a focusable named region. */
export const scrollable = (name: string) =>
  ({
    tabIndex: 0,
    role: 'region',
    'aria-label': `${name} table`,
    sx: { '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 2 } },
  }) as const
