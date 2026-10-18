import useMediaQuery from '@mui/material/useMediaQuery'
import type { ReactNode } from 'react'
import { Alert, AppBar, Box, Button, Container, Link, SkipLink, Toolbar, Typography } from '@/components/ui'
import { SIGN_OUT_FAILED, useLogout } from '@/features/auth/api/mutations'
import { useKnownUser } from '@/features/auth/api/queries'
import { AccountMenu } from './AccountMenu'

const MAIN_ID = 'main-content'

/**
 * The shell every route renders in: a skip link, the top bar with the main navigation and the
 * signed-in user, and the one <main> of the page. Navigation shows only with a session.
 * Below `sm` the user and Sign out go into a menu, so the bar fits 320 px (WCAG 1.4.10).
 */
export function Layout({ children }: { children: ReactNode }) {
  const user = useKnownUser()
  const logout = useLogout()
  // noSsr: read the media query in the first render, so a phone never renders the wide bar first.
  const narrow = useMediaQuery((theme) => theme.breakpoints.down('sm'), { noSsr: true })
  // aria-disabled and a guard, not disabled: disabling the focused button drops focus to the
  // body, and after a failed sign-out the user tries again from here.
  const signOut = () => {
    if (!logout.isPending) logout.mutate()
  }
  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <SkipLink target={MAIN_ID} />
      <AppBar position="static" elevation={0}>
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
                <AccountMenu username={user.username} pending={logout.isPending} onSignOut={signOut} />
              ) : (
                <>
                  <Typography component="p" sx={{ minWidth: 0 }}>
                    Signed in as {user.username}
                  </Typography>
                  <Button color="inherit" variant="outlined" aria-disabled={logout.isPending} onClick={signOut}>
                    Sign out
                  </Button>
                </>
              )}
            </>
          )}
        </Toolbar>
      </AppBar>
      {/* Under the button that failed, in view: the global notices render after the page. */}
      {user && logout.isError && (
        <Alert severity="error" square onClose={() => logout.reset()}>
          {SIGN_OUT_FAILED}
        </Alert>
      )}
      {/* tabIndex -1: the skip link moves focus here, not only the scroll position. */}
      <Container component="main" id={MAIN_ID} tabIndex={-1} maxWidth="lg" sx={{ py: 4, flex: 1, outline: 'none' }}>
        {children}
      </Container>
    </Box>
  )
}
