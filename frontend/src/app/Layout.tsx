import useMediaQuery from '@mui/material/useMediaQuery'
import { useTheme } from '@mui/material/styles'
import { useParams, useRouter, useRouterState } from '@tanstack/react-router'
import { type ReactNode, useEffect, useRef } from 'react'
import { Alert, AppBar, Box, Container, Link, SkipLink, Toolbar } from '@/components/ui'
import { SIGN_OUT_FAILED, useLogout } from '@/features/auth/api/mutations'
import { useKnownUser } from '@/features/auth/api/queries'
import { Notifications } from '@/components/Notifications'
import { TopSearch } from '@/features/search/components/TopSearch'
import { AccountMenu } from './AccountMenu'
import { LabPicker } from './LabPicker'
import { LabTabs } from './LabTabs'
import { focusPageStart, movesFocus } from './page-focus'

const MAIN_ID = 'main-content'

/**
 * The shell every route renders in: a skip link, the top bar (name, lab picker, search,
 * account menu), the lab's section tabs on a lab's pages, and the one <main> of the page. They
 * show only with a session. The bar wraps instead of overflowing, so it fits 320 px (WCAG 1.4.10).
 */
export function Layout({ children }: { children: ReactNode }) {
  const user = useKnownUser()
  const logout = useLogout()
  const router = useRouter()
  const { labId } = useParams({ strict: false })
  // /labs/<id>/<section>: the section the lab picker keeps when the lab changes.
  const section = useRouterState({ select: (state) => state.location.pathname.split('/')[3] })
  // Sign out, or the menu button that holds it: where focus goes when the failure notice closes.
  const accountControl = useRef<HTMLButtonElement>(null)
  // Below sm the search is a button that opens a full-width field under the bar (#76).
  const compact = useMediaQuery(useTheme().breakpoints.down('sm'), { noSsr: true })

  // After a navigation to another page, focus its h1 (or main), so a screen reader reads the new
  // page and Tab starts there, not on the link that is gone (WCAG 2.4.3).
  useEffect(
    () =>
      router.subscribe('onRendered', (event) => {
        const main = document.getElementById(MAIN_ID)
        if (main && movesFocus(event)) focusPageStart(main)
      }),
    [router],
  )

  // aria-disabled and a guard, not disabled: disabling the focused button drops focus to the
  // body, and after a failed sign-out the user tries again from here.
  const signOut = () => {
    if (!logout.isPending) logout.mutate()
  }
  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <SkipLink target={MAIN_ID} />
      {/* Not printed: a printed page (a shipment's document) shows only what it is about. */}
      <AppBar position="static" color="default" elevation={0} sx={{ displayPrint: 'none', bgcolor: 'background.paper', color: 'text.primary', borderBottom: 1, borderColor: 'divider' }}>
        <Toolbar disableGutters sx={{ gap: 1.5, py: 0.75, px: { xs: 1, sm: 2 }, minHeight: 48, flexWrap: 'wrap' }}>
          <Link to="/" aria-label="Culture Collection" underline="none" color="text.primary" sx={{ display: 'flex', alignItems: 'center', gap: 1, fontWeight: 600 }}>
            <Box
              component="span"
              aria-hidden
              sx={{ display: 'grid', placeItems: 'center', width: 28, height: 28, borderRadius: 1, bgcolor: 'primary.main', color: 'primary.contrastText', fontSize: '0.8rem', fontWeight: 700 }}
            >
              CC
            </Box>
            Culture Collection
          </Link>
          {user && (
            <>
              <LabPicker labId={labId} section={section} />
              <Box sx={{ flexGrow: 1 }} />
              <TopSearch compact={compact} />
              <AccountMenu ref={accountControl} username={user.username} pending={logout.isPending} onSignOut={signOut} />
            </>
          )}
        </Toolbar>
      </AppBar>
      {user && labId !== undefined && <LabTabs labId={labId} />}
      {/* Under the button that failed, in view. Closing
          it would drop the focus with its close button, so focus goes back to sign out. */}
      {user && logout.isError && (
        <Alert
          severity="error"
          square
          onClose={() => {
            logout.reset()
            accountControl.current?.focus()
          }}
        >
          {SIGN_OUT_FAILED}
        </Alert>
      )}
      {/* The global notices (a failed save nobody handled): in view, above the page they came from. */}
      <Notifications />
      {/* tabIndex -1: the skip link and a navigation move focus here, not only the scroll position. */}
      <Container component="main" id={MAIN_ID} tabIndex={-1} maxWidth="lg" sx={{ py: 4, flex: 1, outline: 'none' }}>
        {children}
      </Container>
    </Box>
  )
}
