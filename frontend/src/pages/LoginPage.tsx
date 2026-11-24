import { getRouteApi, useNavigate } from '@tanstack/react-router'
import { Alert, Container, PageTitle, Paper, Typography } from '@/components/ui'
import { SignIn } from '@/features/auth/components/SignIn'
import { safeRedirect } from '@/lib/safe'

const route = getRouteApi('/login')

export function LoginPage() {
  const { redirect, signedOut, sessionEnded } = route.useSearch()
  const navigate = useNavigate()
  return (
    <Container component="section" maxWidth="xs" disableGutters>
      <PageTitle>Sign in</PageTitle>
      <Paper variant="outlined" sx={{ p: 3 }}>
        <Typography component="h1" variant="h4" gutterBottom>
          Sign in
        </Typography>
        {/* status, not alert: a confirmation the user expects, read when they get to it. */}
        {signedOut && (
          // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- MUI Alert owns its root element and defaults to role="alert"; role="status" is what <output> would give
          <Alert severity="info" role="status" sx={{ mb: 2 }}>
            You have been signed out.
          </Alert>
        )}
        {sessionEnded && !signedOut && (
          // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- MUI Alert owns its root element and defaults to role="alert"; role="status" is what <output> would give
          <Alert severity="info" role="status" sx={{ mb: 2 }}>
            Your session ended. Sign in again to go back to where you were.
          </Alert>
        )}
        <SignIn onSignedIn={() => void navigate({ href: safeRedirect(redirect), replace: true })} />
      </Paper>
    </Container>
  )
}
