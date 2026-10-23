import { PageTitle, Typography } from '@/components/ui'
import { Home } from '@/features/home/components/Home'

/** Thin: the feature shows what waits, the labs, the activity and the actions. */
export function HomePage() {
  return (
    <section>
      <PageTitle>Home</PageTitle>
      <Typography component="h1" variant="h4" gutterBottom>
        Home
      </Typography>
      <Home />
    </section>
  )
}
