import { alpha, createTheme } from '@mui/material/styles'

/** The tones of a status chip: what a word like Released, Held or Regulated means at a glance. */
export type StatusTone = 'success' | 'warning' | 'danger' | 'info' | 'regulated' | 'neutral'
export type StatusColors = { bg: string; fg: string; border: string }

declare module '@mui/material/styles' {
  interface Palette {
    /** The border of an input or an outlined button: 3:1 against the surface (WCAG 1.4.11). */
    controlBorder: string
    status: Record<StatusTone, StatusColors>
  }
  interface PaletteOptions {
    controlBorder?: string
    status?: Record<StatusTone, StatusColors>
  }
}

/** Monospace for accession numbers, vial labels, request numbers and hashes (see components/ui/Mono). */
const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'

/*
 * The visual base (issue 30): GitHub's model, dense and plain. Surfaces and text are neutral; colour
 * means something. Teal is the accent (primary actions, focus, the active tab). Links are blue, so
 * they never read as the accent. Status colours (success, warning, error, the status chips) stay apart
 * from the teal. Every text colour below reaches 4.5:1 on the surfaces it is used on, every control
 * border and focus ring 3:1, in both schemes: src/app/theme.test.ts computes them from these values
 * and e2e/contrast.spec.ts measures them in the browser, hover and focus included.
 *
 *            light      dark
 * surface    #f6f8fa    #0d1117   (page)      paper #ffffff / #151b23 (tables, dialogs, bar)
 * text       #1f2328    #e6edf3   secondary #59636e / #9198a1
 * primary    #0f766e    #2dd4bf   text on it #ffffff / #04201d, hover #115e59 / #5eead4
 * link       #0757c4    #4493f8   hover #0550ae / #79c0ff
 */
const light = {
  palette: {
    mode: 'light' as const,
    primary: { main: '#0f766e', dark: '#115e59', contrastText: '#ffffff' },
    error: { main: '#cf222e', dark: '#a40e26', contrastText: '#ffffff' },
    warning: { main: '#9a6700', dark: '#7d4e00', contrastText: '#ffffff' },
    success: { main: '#1a7f37', dark: '#116329', contrastText: '#ffffff' },
    info: { main: '#0757c4', dark: '#0550ae', contrastText: '#ffffff' },
    text: { primary: '#1f2328', secondary: '#59636e', disabled: '#818b98' },
    background: { default: '#f6f8fa', paper: '#ffffff' },
    divider: '#d1d9e0',
    action: { hover: alpha('#1f2328', 0.04), selected: alpha('#1f2328', 0.08) },
    controlBorder: '#6e7781',
    status: {
      success: { bg: '#dafbe1', fg: '#116329', border: '#4ac26b' },
      warning: { bg: '#fff8c5', fg: '#7d4e00', border: '#d4a72c' },
      danger: { bg: '#ffebe9', fg: '#a40e26', border: '#ff8182' },
      info: { bg: '#ddf4ff', fg: '#0550ae', border: '#54aeff' },
      regulated: { bg: '#fbefff', fg: '#6639ba', border: '#c297ff' },
      neutral: { bg: '#eaeef2', fg: '#424a53', border: '#8c959f' },
    },
  },
}

const dark = {
  palette: {
    mode: 'dark' as const,
    primary: { main: '#2dd4bf', dark: '#5eead4', contrastText: '#04201d' },
    error: { main: '#ff7b72', dark: '#ffa198', contrastText: '#0d1117' },
    warning: { main: '#d29922', dark: '#e3b341', contrastText: '#0d1117' },
    success: { main: '#3fb950', dark: '#56d364', contrastText: '#0d1117' },
    info: { main: '#4493f8', dark: '#79c0ff', contrastText: '#0d1117' },
    text: { primary: '#e6edf3', secondary: '#9198a1', disabled: '#6e7681' },
    background: { default: '#0d1117', paper: '#151b23' },
    divider: '#3d444d',
    action: { hover: alpha('#e6edf3', 0.06), selected: alpha('#e6edf3', 0.12) },
    controlBorder: '#8b949e',
    status: {
      success: { bg: '#12261e', fg: '#56d364', border: '#2ea043' },
      warning: { bg: '#272115', fg: '#e3b341', border: '#9e6a03' },
      danger: { bg: '#2d1214', fg: '#ff7b72', border: '#da3633' },
      info: { bg: '#121d2f', fg: '#79c0ff', border: '#388bfd' },
      regulated: { bg: '#271a3b', fg: '#d2a8ff', border: '#8957e5' },
      neutral: { bg: '#21262d', fg: '#c9d1d9', border: '#6e7681' },
    },
  },
}

/** Both schemes, for the contrast test. */
export const schemes = { light: light.palette, dark: dark.palette }

/**
 * One definition for light and dark. CSS variables follow the scheme in [data-color-scheme] on <html>,
 * which MUI sets from the system setting or from the choice the user made in the account menu
 * (app/scheme.ts remembers it); no inline script is needed (the CSP allows none).
 * System fonts: the CSP loads fonts only from our origin, and we ship none.
 *
 * focusVisible: without it MUI draws no keyboard focus ring on buttons (ButtonBase sets
 * outline 0), only a faint background. true gives a 2px solid outline in palette.primary.main,
 * 2px outside the control (@mui/material 9.5.0, styles/focusVisible.js). An outline, unlike a
 * box shadow, stays visible in forced colours. Primary has 3:1 or more on the page and on paper in
 * both schemes (the top bar is paper too, so no control needs another ring colour there).
 * e2e/a11y.spec.ts measures every case.
 *
 * Density: compact. Small buttons, inputs and table cells; link and button targets keep 24 by 24 px
 * (WCAG 2.5.8): e2e/shell.spec.ts measures them.
 */
export const theme = createTheme({
  cssVariables: { colorSchemeSelector: 'data-color-scheme' },
  colorSchemes: { light, dark },
  focusVisible: true,
  shape: { borderRadius: 6 },
  typography: {
    fontFamily: FONT,
    fontSize: 14,
    h4: { fontSize: '1.5rem', fontWeight: 600, lineHeight: 1.25 },
    h5: { fontSize: '1.125rem', fontWeight: 600, lineHeight: 1.3 },
    h6: { fontSize: '1rem', fontWeight: 600, lineHeight: 1.4 },
    body1: { fontSize: '0.875rem', lineHeight: 1.5 },
    body2: { fontSize: '0.8125rem', lineHeight: 1.5 },
    button: { textTransform: 'none', fontWeight: 500 },
  },
  components: {
    MuiCssBaseline: {
      // A long word (a lab name, a username) breaks instead of widening the page (WCAG 1.4.10).
      styleOverrides: { body: { overflowWrap: 'break-word' } },
    },
    MuiButton: {
      defaultProps: { size: 'small', disableElevation: true },
      styleOverrides: { root: { minHeight: 28, textTransform: 'none' } },
      variants: [
        // Secondary actions are neutral, as on GitHub: the teal is kept for the one primary action.
        {
          props: { variant: 'outlined', color: 'primary' },
          style: ({ theme: t }) => ({
            color: (t.vars ?? t).palette.text.primary,
            borderColor: (t.vars ?? t).palette.controlBorder,
            '&:hover': { borderColor: (t.vars ?? t).palette.text.secondary, backgroundColor: (t.vars ?? t).palette.action.hover },
          }),
        },
        {
          props: { variant: 'outlined', color: 'error' },
          style: ({ theme: t }) => ({ borderColor: (t.vars ?? t).palette.error.main }),
        },
      ],
    },
    MuiTextField: { defaultProps: { size: 'small' } },
    MuiOutlinedInput: {
      styleOverrides: {
        notchedOutline: ({ theme: t }) => ({ borderColor: (t.vars ?? t).palette.controlBorder }),
      },
    },
    MuiCheckbox: { defaultProps: { size: 'small' } },
    MuiTable: { defaultProps: { size: 'small' } },
    MuiTableCell: {
      styleOverrides: {
        root: ({ theme: t }) => ({
          padding: '5px 12px',
          borderColor: (t.vars ?? t).palette.divider,
          // A link in a cell is a target of its own: 24 px high, not a 20 px line of text.
          '& a': { display: 'inline-flex', alignItems: 'center', minHeight: 24 },
        }),
        head: ({ theme: t }) => ({
          fontWeight: 600,
          backgroundColor: (t.vars ?? t).palette.background.default,
        }),
      },
    },
    MuiTableRow: {
      styleOverrides: { root: { '&:last-child td, &:last-child th': { borderBottom: 0 } } },
    },
    MuiPaper: { defaultProps: { elevation: 0 } },
    MuiDialog: {
      styleOverrides: { paper: ({ theme: t }) => ({ border: `1px solid ${(t.vars ?? t).palette.divider}` }) },
    },
    MuiDialogTitle: { styleOverrides: { root: { fontSize: '1.0625rem', fontWeight: 600, padding: '16px 20px 8px' } } },
    MuiDialogContent: { styleOverrides: { root: { padding: '8px 20px' } } },
    MuiDialogActions: { styleOverrides: { root: { padding: '12px 20px 16px', gap: 4 } } },
    MuiLink: {
      defaultProps: { underline: 'always' },
      variants: [
        // Links are blue, not the teal of the accent. color="inherit" links (the shell) keep their own.
        {
          props: { color: 'primary' },
          style: ({ theme: t }) => ({ color: (t.vars ?? t).palette.info.main, '&:hover': { color: (t.vars ?? t).palette.info.dark } }),
        },
      ],
    },
  },
})
