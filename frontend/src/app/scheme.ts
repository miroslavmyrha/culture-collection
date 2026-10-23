import { preferences } from '@/lib/storage'

/** The mode the user chose for this browser; 'system' follows prefers-color-scheme. */
export type SchemeMode = 'system' | 'light' | 'dark'
export const SCHEME_KEY = 'scheme'
export const SCHEME_MODES: readonly SchemeMode[] = ['system', 'light', 'dark']

export const isSchemeMode = (value: unknown): value is SchemeMode => SCHEME_MODES.some((mode) => mode === value)

/**
 * MUI's storage manager for the mode, on our preferences helper (lib/storage.ts: localStorage in
 * try/catch). Where storage fails the app still works: the choice just is not remembered. MUI asks
 * for three keys (mode, light scheme, dark scheme); only the mode is a choice of ours, and a stored
 * value that is not a mode is ignored.
 */
export function schemeStorage({ key }: { key: string }) {
  const none = { get: (fallback: string) => fallback, set: () => undefined, subscribe: () => () => undefined }
  if (key !== SCHEME_KEY) return none
  return {
    get: (fallback: string) => {
      const stored = preferences.get(SCHEME_KEY)
      return isSchemeMode(stored) ? stored : fallback
    },
    set: (value: string) => preferences.set(SCHEME_KEY, value),
    // Another tab's change is not followed: the next load reads it.
    subscribe: () => () => undefined,
  }
}
