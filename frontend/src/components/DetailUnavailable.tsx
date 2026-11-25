import { LoadError } from '@/components/LoadError'
import { PageTitle, Typography } from '@/components/ui'
import { isApiError } from '@/lib/api'

type Query = { isPending: boolean; error: unknown; refetch: () => Promise<unknown> }

type Props = {
  query: Query
  /** What the page shows, as the titles name it: "deposit", "unit". */
  noun: string
  /** Why it is not found; 404 means "not in this lab" as much as "does not exist". */
  notFound: string
}

const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)

/** What a detail page shows while it has nothing to show: loading, not found, or the load error, each with its title (#67). */
export function DetailUnavailable({ query, noun, notFound }: Props) {
  if (query.isPending)
    return (
      <>
        <PageTitle>{`Loading the ${noun}`}</PageTitle>
        <Typography>{`Loading the ${noun}…`}</Typography>
      </>
    )
  if (isApiError(query.error, 404))
    return (
      <>
        <PageTitle>{`${capital(noun)} not found`}</PageTitle>
        <Typography component="h1" variant="h4" gutterBottom>
          {`${capital(noun)} not found`}
        </Typography>
        <Typography>{notFound}</Typography>
      </>
    )
  return (
    <>
      <PageTitle>{`Could not load the ${noun}`}</PageTitle>
      <LoadError what={`the ${noun}`} error={query.error} onRetry={() => void query.refetch()} />
    </>
  )
}
