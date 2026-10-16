/**
 * The single error sink. Replace the default reporter with an error-tracking SDK here and
 * nowhere else (set a release, scrub URLs and personal data before sending).
 * Never pass request bodies, form values or HTML input as context.
 */
export type Reporter = (error: unknown, context: Record<string, string>) => void

// oxlint-disable-next-line no-console -- the default sink until an SDK is wired in
const consoleReporter: Reporter = (error, context) => console.error(error, context)

let reporter: Reporter = consoleReporter

/** Tests swap the sink to record reports instead of printing them. Returns the restore function. */
export function setReporter(next: Reporter): () => void {
  reporter = next
  return () => {
    reporter = consoleReporter
  }
}

export const isAbortError = (error: unknown) =>
  (error instanceof DOMException || error instanceof Error) && error.name === 'AbortError'

export function reportError(error: unknown, context: Record<string, string> = {}): void {
  if (isAbortError(error)) return
  reporter(error, context)
}

/** Promise rejections nobody handled. Aborts are expected (navigation, unmount). */
export function onUnhandledRejection(event: PromiseRejectionEvent): void {
  if (isAbortError(event.reason)) return
  reportError(event.reason, { source: 'unhandledrejection' })
}
