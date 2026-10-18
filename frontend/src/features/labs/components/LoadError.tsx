import { Alert, Button } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { useFocusReturnOnUnmount } from '@/lib/focus'

/**
 * A failed load with a working retry. The text is mapped, never the server's own. A retry that
 * works replaces this alert, and its focused button with it: focus then goes to the heading of
 * the section (useFocusReturnOnUnmount), not to the body.
 */
export function LoadError({ what, error, onRetry }: { what: string; error: unknown; onRetry: () => void }) {
  const remember = useFocusReturnOnUnmount()
  return (
    <Alert
      severity="error"
      action={
        <Button
          color="inherit"
          size="small"
          onClick={(event) => {
            remember(event.currentTarget)
            onRetry()
          }}
        >
          Try again
        </Button>
      }
    >
      Could not load {what}. {errorMessage(error)}
    </Alert>
  )
}
