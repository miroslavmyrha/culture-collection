import { type ErrorComponentProps, Link, useRouter } from '@tanstack/react-router'
import { errorMessage } from '@/lib/api'

export function NotFound() {
  return (
    <main>
      <h1>Page not found</h1>
      <p>The address may be mistyped, or the page was moved.</p>
      <Link to="/">Go to the start page</Link>
    </main>
  )
}

/**
 * Route-level error screen. Generic, mapped text only: the raw message (which may echo server
 * data) is shown in development and never in production. Reporting happens in the router's
 * defaultOnCatch, not here, so a re-render does not report twice.
 */
export function RouteError({ error, reset }: ErrorComponentProps) {
  const router = useRouter()
  const retry = () => {
    reset()
    void router.invalidate()
  }
  return (
    <main role="alert">
      <h1>Something went wrong</h1>
      <p>{errorMessage(error)}</p>
      {import.meta.env.DEV && <pre>{error instanceof Error ? error.message : String(error)}</pre>}
      <button type="button" onClick={retry}>
        Try again
      </button>{' '}
      <button type="button" onClick={() => window.location.reload()}>
        Reload the page
      </button>
    </main>
  )
}

export function Pending() {
  return <p>Loading…</p>
}
