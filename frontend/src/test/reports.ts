import { setReporter } from '@/lib/report'

/** What reportError received during the current test (the sink is swapped in setup.ts). */
export const reported: { error: unknown; context: Record<string, string> }[] = []

export function captureReports(): () => void {
  reported.length = 0
  return setReporter((error, context) => {
    reported.push({ error, context })
  })
}
