import Box from '@mui/material/Box'

/**
 * The first focusable element: keyboard and screen reader users jump past the top bar.
 * Hidden until focused, then shown over the bar.
 */
export function SkipLink({ target }: { target: string }) {
  return (
    <Box
      component="a"
      href={`#${target}`}
      sx={{
        position: 'absolute',
        left: 8,
        top: -48,
        zIndex: 'tooltip',
        p: 1,
        bgcolor: 'background.paper',
        color: 'text.primary',
        // Shown over the top bar: a ring in the text colour, flush with the link, has 3:1 against
        // both the link's paper and the bar in either scheme (the primary ring would vanish on the bar).
        '&:focus': { top: 8, outline: '2px solid', outlineColor: 'text.primary', outlineOffset: 0 },
      }}
    >
      Skip to content
    </Box>
  )
}
