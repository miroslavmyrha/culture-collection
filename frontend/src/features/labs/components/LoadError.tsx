import { Alert, Button } from '@/components/ui'
import { errorMessage } from '@/lib/api'

/** A failed load with a working retry. The text is mapped, never the server's own. */
export function LoadError({ what, error, onRetry }: { what: string; error: unknown; onRetry: () => void }) {
  return (
    <Alert
      severity="error"
      action={
        <Button color="inherit" size="small" onClick={onRetry}>
          Try again
        </Button>
      }
    >
      Could not load {what}. {errorMessage(error)}
    </Alert>
  )
}
