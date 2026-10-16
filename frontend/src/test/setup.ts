// oxlint-disable-next-line import/no-unassigned-import -- registers jest-dom matchers
import '@testing-library/jest-dom/vitest'
// oxlint-disable-next-line import/no-unassigned-import -- same zod settings as main.tsx
import '@/lib/zod-setup'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest'
import { notify } from '@/lib/notify'
import { assertNoConsoleOutput, watchConsole } from './console'
import { resetFactories } from './factories'
import { captureReports } from './reports'
import { server } from './server'

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
