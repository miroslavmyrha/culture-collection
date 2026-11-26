import { waitFor } from '@testing-library/react'

// Kept apart from render.tsx on purpose: setup.ts imports this, and a setup file that imported
// the app would load MUI before a test file's vi.mock of it could take effect.

type Settling = { state: { isLoading: boolean; location: { href: string } } }

// Every router a test renders, so the test's teardown can wait for its navigation (#224).
const routers = new Set<Settling>()

/** Remember a router a test rendered, for settleRouters. */
export function trackRouter(router: Settling) {
  routers.add(router)
}

/**
 * Wait until no router of the test is loading a page, then forget them. A navigation still loading
 * when the test ends finishes after the test environment is gone and fails the run elsewhere
 * (window is not defined). One that never ends fails the test that started it, by name.
 */
export async function settleRouters() {
  try {
    for (const router of routers) {
      await waitFor(() => {
        if (router.state.isLoading)
          throw new Error(`A navigation to ${router.state.location.href} is still loading: wait for the page it opens before the test ends.`)
      })
    }
  } finally {
    routers.clear()
  }
}
