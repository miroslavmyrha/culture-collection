// oxlint-disable-next-line import/no-unassigned-import -- registers jest-dom matchers
import '@testing-library/jest-dom/vitest'
// oxlint-disable-next-line import/no-unassigned-import -- same zod settings as main.tsx
import '@/lib/zod-setup'
import { cleanup, configure } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest'
import { notify } from '@/lib/notify'
import { assertNoConsoleOutput, watchConsole } from './console'
import { resetFactories } from './factories'
import { captureReports } from './reports'
import { server } from './server'

// How long findBy and waitFor wait for a state, in place of a timeout on every call (#60). The default
// is 1 s. The slowest test of the suite took 13.1 s with 8 busy processes on 4 cores (vitest.config.ts),
// so 20 s is above that and below the test budget of 40 s: a state that never comes fails here, with the
// DOM in the message, not as a test timeout.
configure({ asyncUtilTimeout: 20_000 })

// jsdom has no layout: its window.scrollTo only prints "Not implemented" on every
// navigation (the router restores scroll positions). A no-op keeps the output clean.
Object.defineProperty(window, 'scrollTo', { value: () => undefined, writable: true })

let restoreReporter: () => void = () => {}

// MSW 3 renamed onUnhandledRequest to onUnhandledFrame (it also covers WebSockets).
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  watchConsole()
  restoreReporter = captureReports()
})
afterEach(() => {
  cleanup()
  server.resetHandlers()
  restoreReporter()
  notify.clear()
  resetFactories()
  localStorage.clear()
  sessionStorage.clear()
  document.cookie = 'csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
  assertNoConsoleOutput()
})
afterAll(() => server.close())
