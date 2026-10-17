import { createTheme } from '@mui/material/styles'

/**
 * One definition for light and dark. CSS variables with the default media selector follow
 * prefers-color-scheme in CSS, so no inline script is needed (the CSP allows none).
 * System fonts: the CSP loads fonts only from our origin, and we ship none.
 */
export const theme = createTheme({
  cssVariables: true,
  colorSchemes: { light: true, dark: true },
  typography: {
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  },
})
