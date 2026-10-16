import { describe, expect, it, vi } from 'vitest'
import { handlePreloadError } from './stale-chunks'

function setup(now: number) {
  const reload = vi.fn<() => void>()
  const event = new Event('vite:preloadError', { cancelable: true })
  return { reload, event, deps: { reload, storage: sessionStorage, now } }
}

describe('handlePreloadError', () => {
  it('reloads once and stops the error', () => {
    const { reload, event, deps } = setup(100_000)
    handlePreloadError(event, deps)
    expect(reload).toHaveBeenCalledOnce()
    expect(event.defaultPrevented).toBe(true)
  })

  it('does not loop: a second failure within 10 s reaches the error screen', () => {
    handlePreloadError(setup(100_000).event, setup(100_000).deps)
    const { reload, event, deps } = setup(105_000)
    handlePreloadError(event, deps)
    expect(reload).not.toHaveBeenCalled()
    expect(event.defaultPrevented).toBe(false)
  })

  it('reloads again after the cooldown', () => {
    handlePreloadError(setup(100_000).event, setup(100_000).deps)
    const { reload, deps, event } = setup(111_000)
    handlePreloadError(event, deps)
    expect(reload).toHaveBeenCalledOnce()
  })

  it('never reloads without storage', () => {
    const { reload, event } = setup(1)
    const broken = { getItem: () => { throw new Error('denied') }, setItem: () => {} }
    handlePreloadError(event, { reload, storage: broken, now: 1 })
    expect(reload).not.toHaveBeenCalled()
  })
})
