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

// An encoded slash or backslash in the path: no route of ours has one, and a layer that
// decodes it (the router, a proxy) may turn /%2F/evil.com into //evil.com.
const ENCODED_SLASH = /%2f|%5c/i

/**
 * Paths never worth returning to: /login in any spelling the router matches (/login/, /LOGIN,
 * /%6Cogin), an encoded slash, and a malformed escape that no layer decodes the same way.
 */
function isRefusedPath(pathname: string): boolean {
  if (ENCODED_SLASH.test(pathname)) return true
  try {
    return decodeURIComponent(pathname).replace(/\/+$/, '').toLowerCase() === '/login'
  } catch {
    return true
  }
}

/**
 * A same-origin path to go to after login, or the fallback. Compares parsed origins:
 * a regex such as /^\/[^/]/ lets /\evil.com and /\t/evil.com through.
 * The output is checked as well as the input: /..//evil.com resolves on our origin, but its
 * normalised path //evil.com is protocol-relative again and leaves the site when used as a URL.
 * So the returned path must not start with // or /\, and must resolve to our origin once more.
 */
export function safeRedirect(raw: unknown, fallback = '/'): string {
  if (typeof raw !== 'string' || !raw.startsWith('/')) return fallback
  const origin = window.location.origin
  try {
    const url = new URL(raw, origin)
    if (url.origin !== origin) return fallback
    if (isRefusedPath(url.pathname)) return fallback
    const path = url.pathname + url.search + url.hash
    // The output again: a path that starts with // or /\ is protocol-relative, and it must
    // still resolve to our origin when the router or the browser reads it as a URL.
    if (path.startsWith('//') || path.startsWith('/\\')) return fallback
    if (new URL(path, origin).origin !== origin) return fallback
    return path
  } catch {
    return fallback
  }
}

/** window.open does not imply noopener (anchors do), so every external open goes through here. */
export function openExternal(raw: string): void {
  const href = safeHref(raw)
  if (href) window.open(href, '_blank', 'noopener,noreferrer')
}
