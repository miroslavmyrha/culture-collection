const KEY = 'chunk-reload-at'
const COOLDOWN_MS = 10_000

type Deps = { reload: () => void; storage: Pick<Storage, 'getItem' | 'setItem'> | undefined; now: number }

/**
 * After a deploy an open tab asks for chunks that no longer exist. Reload once to get the new
 * index.html; if that already happened in the last 10 s, let the error reach the error screen
 * instead of looping.
 */
export function handlePreloadError(event: Event, deps: Deps): void {
  try {
    const last = Number(deps.storage?.getItem(KEY) ?? 0)
    if (deps.now - last < COOLDOWN_MS) return
    deps.storage?.setItem(KEY, String(deps.now))
  } catch {
    return // no sessionStorage: a reload could loop, so do not reload
  }
  event.preventDefault()
  deps.reload()
}

export function installStaleChunkReload(): void {
  window.addEventListener('vite:preloadError', (event) => {
    let storage: Storage | undefined
    try {
      storage = window.sessionStorage
    } catch {
      storage = undefined
    }
    handlePreloadError(event, { reload: () => window.location.reload(), storage, now: Date.now() })
  })
}
