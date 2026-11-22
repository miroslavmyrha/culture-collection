import { Container, PageTitle, Typography } from '@/components/ui'
import { FactorList } from '@/features/auth/components/FactorList'

export function SecurityPage() {
  return (
    <Container component="section" maxWidth="sm" disableGutters>
      <PageTitle>Sign-in and security</PageTitle>
      <Typography component="h1" variant="h4" gutterBottom>
        Sign-in and security
      </Typography>
      <FactorList />
    </Container>
  )
}
