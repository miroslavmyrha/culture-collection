const ALLOWED_PROTOCOLS = new Set(['http:', 'https:', 'mailto:'])

/**
 * Returns the parsed href when it is safe to put into href or src, otherwise undefined.
 * The URL parser already strips leading spaces, tabs and newlines the way browsers do, so the
 * input is not cleaned by hand (that would corrupt valid URLs such as spaces in a path).
 */
export function safeHref(raw: string | null | undefined): string | undefined {
  if (!raw) return undefined
  let url: URL
  try {
    url = new URL(raw, window.location.origin)
  } catch {
    return undefined
  }
  if (!ALLOWED_PROTOCOLS.has(url.protocol)) return undefined
  // https://app.example@evil.com reads like our host but goes to evil.com.
  if (url.username || url.password) return undefined
  return url.href
}

/**
 * A same-origin path to go to after login, or the fallback. Compares parsed origins:
 * a regex such as /^\/[^/]/ lets /\evil.com and /\t/evil.com through.
 */
export function safeRedirect(raw: unknown, fallback = '/'): string {
  if (typeof raw !== 'string' || !raw.startsWith('/')) return fallback
  try {
    const url = new URL(raw, window.location.origin)
    if (url.origin !== window.location.origin) return fallback
    if (url.pathname === '/login') return fallback
    return url.pathname + url.search + url.hash
  } catch {
    return fallback
  }
}

/** window.open does not imply noopener (anchors do), so every external open goes through here. */
export function openExternal(raw: string): void {
  const href = safeHref(raw)
  if (href) window.open(href, '_blank', 'noopener,noreferrer')
}
