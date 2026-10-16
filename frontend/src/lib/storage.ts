/** UI preferences only. Never tokens, secrets or personal data. Tolerates private mode. */
export const preferences = {
  get(key: string): string | null {
    try {
      return localStorage.getItem(`pref:${key}`)
    } catch {
      return null
    }
  },
  set(key: string, value: string): void {
    try {
      localStorage.setItem(`pref:${key}`, value)
    } catch {
      /* storage unavailable: preferences are optional */
    }
  },
}
