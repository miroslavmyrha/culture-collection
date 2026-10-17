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
        '&:focus': { top: 8 },
      }}
    >
      Skip to content
    </Box>
  )
}
