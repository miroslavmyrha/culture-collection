import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { render } from '@testing-library/react'
import { useEffect } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { useUnsavedGuard } from './UnsavedGuard'

/** Mounts a component that uses the guard; returns what it registered with the router's history. */
async function mount(dirty: boolean) {
  const history = createMemoryHistory({ initialEntries: ['/'] })
  const block = vi.spyOn(history, 'block')
  const handle: { allowLeaving?: () => void } = {}
  function Form() {
    const guard = useUnsavedGuard(dirty)
    useEffect(() => {
      handle.allowLeaving = guard.allowLeaving
    })
    return guard.dialog
  }
  const root = createRootRoute({ component: Form })
  const router = createRouter({ routeTree: root.addChildren([createRoute({ getParentRoute: () => root, path: '/' })]), history })
  await router.load()
  render(<RouterProvider router={router} />)
  const registered = block.mock.calls.at(-1)?.[0]
  if (!registered) throw new Error('the guard registered no blocker')
  return { registered, allowLeaving: () => handle.allowLeaving?.() }
}

const closesTab = (blocker: { enableBeforeUnload?: boolean | (() => boolean) }) => (typeof blocker.enableBeforeUnload === 'function' ? blocker.enableBeforeUnload() : blocker.enableBeforeUnload)

// jsdom has no tab to close, and a memory history never listens for beforeunload: the guard hands
// the browser history a condition, and this checks the condition.
describe('useUnsavedGuard', () => {
  it('asks the browser to confirm closing the tab only while there are unsaved changes', async () => {
    expect(closesTab((await mount(true)).registered)).toBe(true)
    expect(closesTab((await mount(false)).registered)).toBe(false)
  })

  it('stops asking once the form says it is leaving on purpose', async () => {
    const { registered, allowLeaving } = await mount(true)
    allowLeaving()
    expect(closesTab(registered)).toBe(false)
  })
})
