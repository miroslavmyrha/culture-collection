import { vi } from 'vitest'

/** Unexpected console.error and console.warn fail the test (act, key and prop warnings are bugs). */
let output: string[] = []
let allowed: RegExp[] = []

export function watchConsole(): void {
  output = []
  allowed = []
  for (const level of ['error', 'warn'] as const) {
    vi.spyOn(console, level).mockImplementation((...args: unknown[]) => {
      const text = args.map((a) => (a instanceof Error ? a.message : String(a))).join(' ')
      if (!allowed.some((re) => re.test(text))) output.push(`console.${level}: ${text}`)
    })
  }
}

/** A test that expects a log says so explicitly. */
export function allowConsole(pattern: RegExp): void {
  allowed.push(pattern)
}

export function assertNoConsoleOutput(): void {
  if (output.length > 0) throw new Error(`Unexpected console output:\n${output.join('\n')}`)
}
