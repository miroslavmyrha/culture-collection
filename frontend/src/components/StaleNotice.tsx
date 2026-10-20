import { Alert, Box, Button } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { useFocusReturnOnUnmount } from '@/lib/focus'

/** What the notice reads of a query; a UseQueryResult has all of it. */
type Query = { data: unknown; error: unknown; isError: boolean; isFetching: boolean; refetch: () => Promise<unknown> }

/**
 * A refresh of data already on screen failed. TanStack Query keeps the data when a refetch
 * fails, so the screen stays, with its open forms and dialogs and what was typed in them, and
 * this line says the data may be out of date. A screen shows the full error (LoadError) only
 * while it has no data at all.
 *
 * A polite status, never focused. It mounts only while stale: an empty live region on every
 * page would be an empty status line for screen reader users. A retry that works removes the
 * notice and its focused button: focus then goes to the section heading (useFocusReturnOnUnmount).
 */
export function StaleNotice({ what, query }: { what: string; query: Query }) {
  if (!query.isError || query.data === undefined) return null
  return <Stale what={what} query={query} />
}

function Stale({ what, query }: { what: string; query: Query }) {
  const remember = useFocusReturnOnUnmount()
  // The output element is the polite status; the Alert inside only draws it (no role of its own).
  return (
    <Box component="output" sx={{ display: 'block', mb: 2 }}>
      <Alert
        severity="warning"
        role="none"
        action={
          <Button
            color="inherit"
            size="small"
            aria-disabled={query.isFetching}
            sx={{ '&[aria-disabled="true"]': { cursor: 'progress' } }}
            onClick={(event) => {
              // aria-disabled keeps the focus on the button, so guard here
              if (query.isFetching) return
              remember(event.currentTarget)
              void query.refetch()
            }}
          >
            Try again
          </Button>
        }
      >
        Could not refresh {what}. What you see may be out of date. {errorMessage(query.error)}
      </Alert>
    </Box>
  )
}
