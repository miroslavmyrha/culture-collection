import { createTheme } from '@mui/material/styles'

/**
 * One definition for light and dark. CSS variables with the default media selector follow
 * prefers-color-scheme in CSS, so no inline script is needed (the CSP allows none).
 * System fonts: the CSP loads fonts only from our origin, and we ship none.
 *
 * focusVisible: without it MUI draws no keyboard focus ring on buttons (ButtonBase sets
 * outline 0), only a faint background. true gives a 2px solid outline in palette.primary.main,
 * 2px outside the control (@mui/material 9.5.0, styles/focusVisible.js). An outline, unlike a
 * box shadow, stays visible in forced colours. On paper the primary colour has 3:1 or more in
 * both schemes, but an outset ring has to contrast with the surface the control sits on, and
 * on the primary AppBar that surface is the ring's own colour (1:1). There the ring takes the
 * bar's text colour (currentColor of the inherit-coloured controls): white on the light bar,
 * the text colour on the dark one. e2e/a11y.spec.ts measures every case.
 */
export const theme = createTheme({
  cssVariables: true,
  colorSchemes: { light: true, dark: true },
  focusVisible: true,
  typography: {
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  },
  components: {
    MuiCssBaseline: {
      // A long word (a lab name, a username) breaks instead of widening the page (WCAG 1.4.10).
      styleOverrides: { body: { overflowWrap: 'break-word' } },
    },
    MuiAppBar: {
      styleOverrides: {
        // Three classes: more specific than the controls' own `.MuiButton-root.Mui-focusVisible`,
        // whatever order emotion inserts the rules in.
        root: {
          '& .MuiButtonBase-root.Mui-focusVisible, & .MuiLink-root.Mui-focusVisible': { outlineColor: 'currentColor' },
        },
      },
    },
  },
})
