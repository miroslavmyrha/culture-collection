import { PageTitle, Typography } from '@/components/ui'

export function HomePage() {
  return (
    <section>
      <PageTitle>Home</PageTitle>
      <Typography component="h1" variant="h4" gutterBottom>
        Home
      </Typography>
      <Typography>Strains, storage and distribution will appear here.</Typography>
    </section>
  )
}
