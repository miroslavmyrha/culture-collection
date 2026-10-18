import { type ErrorComponentProps, Link, useRouter } from '@tanstack/react-router'
import type { MouseEvent } from 'react'
import { PageTitle } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { focusLost, rememberFocus } from '@/lib/focus'

export function NotFound() {
  return (
    <section>
      <PageTitle>Page not found</PageTitle>
      <h1>Page not found</h1>
      <p>The address may be mistyped, or the page was moved.</p>
      <Link to="/">Go to the start page</Link>
    </section>
  )
}

/**
 * Route-level error screen. Generic, mapped text only: the raw message (which may echo server
 * data) is shown in development and never in production. Reporting happens in the router's
 * defaultOnCatch, not here, so a re-render does not report twice.
 */
export function RouteError({ error, reset }: ErrorComponentProps) {
  const router = useRouter()
  // A retry that works replaces this screen, and the focused button with it. The router mounts
  // this screen again before the page comes, so focus is placed once the reload has finished
  // (invalidate resolves after the render): on the page's h1, not in the passing error screen.
  const retry = (event: MouseEvent<HTMLButtonElement>) => {
    const spot = rememberFocus(event.currentTarget)
    reset()
    void router.invalidate().then(() => {
      if (focusLost()) spot.restore()
    })
  }
  return (
    <section role="alert">
      <PageTitle>Something went wrong</PageTitle>
      <h1>Something went wrong</h1>
      <p>{errorMessage(error)}</p>
      {import.meta.env.DEV && <pre>{error instanceof Error ? error.message : String(error)}</pre>}
      <button type="button" onClick={retry}>
        Try again
      </button>{' '}
      <button type="button" onClick={() => window.location.reload()}>
        Reload the page
      </button>
    </section>
  )
}

export function Pending() {
  return (
    <>
      <PageTitle>Loading</PageTitle>
      <p>Loading…</p>
    </>
  )
}
