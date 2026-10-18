import type { ReactNode } from 'react'
import { AppBar, Box, Button, Container, Link, SkipLink, Toolbar, Typography } from '@/components/ui'
import { useLogout } from '@/features/auth/api/mutations'
import { useKnownUser } from '@/features/auth/api/queries'

const MAIN_ID = 'main-content'

/**
 * The shell every route renders in: a skip link, the top bar with the main navigation and the
 * signed-in user, and the one <main> of the page. Navigation shows only with a session.
 */
export function Layout({ children }: { children: ReactNode }) {
  const user = useKnownUser()
  const logout = useLogout()
  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <SkipLink target={MAIN_ID} />
      <AppBar position="static" elevation={0}>
        <Toolbar sx={{ gap: 3 }}>
          <Typography component="p" variant="h6">
            <Link to="/" color="inherit" underline="none">
              Culture collection
            </Link>
          </Typography>
          {user && (
            <>
              <Box component="nav" aria-label="Main" sx={{ flexGrow: 1, display: 'flex', gap: 2 }}>
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
              <Typography component="p">Signed in as {user.username}</Typography>
              {/* aria-disabled and a guard, not disabled: disabling the focused button drops focus to
                  the body, and after a failed sign-out the user tries again from here. */}
              <Button
                color="inherit"
                variant="outlined"
                aria-disabled={logout.isPending}
                onClick={() => {
                  if (!logout.isPending) logout.mutate()
                }}
              >
                Sign out
              </Button>
            </>
          )}
        </Toolbar>
      </AppBar>
      {/* tabIndex -1: the skip link moves focus here, not only the scroll position. */}
      <Container component="main" id={MAIN_ID} tabIndex={-1} maxWidth="lg" sx={{ py: 4, flex: 1, outline: 'none' }}>
        {children}
      </Container>
    </Box>
  )
}
