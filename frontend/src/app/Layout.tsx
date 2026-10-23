import useMediaQuery from '@mui/material/useMediaQuery'
import { useRouter } from '@tanstack/react-router'
import { type ReactNode, useEffect, useRef } from 'react'
import { Alert, AppBar, Box, Button, Container, Link, SkipLink, Toolbar, Typography } from '@/components/ui'
import { SIGN_OUT_FAILED, useLogout } from '@/features/auth/api/mutations'
import { useKnownUser } from '@/features/auth/api/queries'
import { AccountMenu } from './AccountMenu'
import { focusPageStart, movesFocus } from './page-focus'

const MAIN_ID = 'main-content'

/**
 * The shell every route renders in: a skip link, the top bar with the main navigation and the
 * signed-in user, and the one <main> of the page. Navigation shows only with a session.
 * Below `sm` the user and Sign out go into a menu, so the bar fits 320 px (WCAG 1.4.10).
 */
export function Layout({ children }: { children: ReactNode }) {
  const user = useKnownUser()
  const logout = useLogout()
  const router = useRouter()
  // noSsr: read the media query in the first render, so a phone never renders the wide bar first.
  const narrow = useMediaQuery((theme) => theme.breakpoints.down('sm'), { noSsr: true })
  // Sign out, or the menu button that holds it: where focus goes when the failure notice closes.
  const accountControl = useRef<HTMLButtonElement>(null)

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
      <AppBar position="static" elevation={0} sx={{ displayPrint: 'none' }}>
        {/* Wraps instead of overflowing: at 320 px the title, the links and the menu take two rows. */}
        <Toolbar sx={{ flexWrap: 'wrap', columnGap: 3, rowGap: 1, py: 1 }}>
          <Typography component="p" variant="h6" sx={{ minWidth: 0 }}>
            <Link to="/" color="inherit" underline="none">
              Culture collection
            </Link>
          </Typography>
          {user && (
            <>
              <Box component="nav" aria-label="Main" sx={{ flexGrow: 1, display: 'flex', flexWrap: 'wrap', columnGap: 2, minWidth: 0 }}>
                {/* includeSearch false: filters or tabs in the URL do not make it a different page. */}
                <Link to="/" color="inherit" activeOptions={{ exact: true, includeSearch: false }}>
                  Home
                </Link>
                {/* Not exact: a lab's page is under Labs too. Without exact the router compares search
                    only on the link's own keys (none here), so includeSearch is kept for the day the
                    link carries a search (@tanstack/react-router 1.170.44, link.js:36-37). */}
                <Link to="/labs" color="inherit" activeOptions={{ includeSearch: false }}>
                  Labs
                </Link>
              </Box>
              {narrow ? (
                <AccountMenu ref={accountControl} username={user.username} pending={logout.isPending} onSignOut={signOut} />
              ) : (
                <>
                  <Typography component="p" sx={{ minWidth: 0 }}>
                    Signed in as {user.username}
                  </Typography>
                  <Button ref={accountControl} color="inherit" variant="outlined" aria-disabled={logout.isPending} onClick={signOut}>
                    Sign out
                  </Button>
                </>
              )}
            </>
          )}
        </Toolbar>
      </AppBar>
      {/* Under the button that failed, in view: the global notices render after the page. Closing
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
      {/* tabIndex -1: the skip link and a navigation move focus here, not only the scroll position. */}
      <Container component="main" id={MAIN_ID} tabIndex={-1} maxWidth="lg" sx={{ py: 4, flex: 1, outline: 'none' }}>
        {children}
      </Container>
    </Box>
  )
}
