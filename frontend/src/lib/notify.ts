import { useSyncExternalStore } from 'react'

/** App-wide messages (the global mutation error net). Errors only: success is shown in place. */
export type Notice = { id: number; message: string }

let notices: readonly Notice[] = []
let nextId = 1
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((listener) => listener())

export const notify = {
  /** Shows a message once; the same text is not stacked twice. */
  error: (message: string): void => {
    if (notices.some((n) => n.message === message)) return
    notices = [...notices, { id: nextId++, message }]
    emit()
  },
  dismiss: (id: number): void => {
    notices = notices.filter((n) => n.id !== id)
    emit()
  },
  clear: (): void => {
    notices = []
    emit()
  },
  subscribe: (listener: () => void): (() => void) => {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
  get: (): readonly Notice[] => notices,
}

export function useNotices(): readonly Notice[] {
  return useSyncExternalStore(notify.subscribe, notify.get)
}
