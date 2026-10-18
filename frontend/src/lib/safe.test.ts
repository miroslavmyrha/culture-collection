import { describe, expect, it } from 'vitest'
import { safeHref, safeRedirect } from './safe'

describe('safeHref', () => {
  it.each([
    ['https://example.org/a', 'https://example.org/a'],
    ['http://example.org', 'http://example.org/'],
    ['mailto:lab@example.org', 'mailto:lab@example.org'],
    ['/relative', `${window.location.origin}/relative`],
  ])('allows %s as %s', (url, href) => {
    expect(safeHref(url)).toBe(href)
  })

  it.each(['javascript:alert(1)', 'JaVaScRiPt:alert(1)', 'java\tscript:alert(1)', ' javascript:x', '\njavascript:x', 'data:text/html,<script>', 'vbscript:x'])(
    'rejects %j',
    (url) => {
      expect(safeHref(url)).toBeUndefined()
    },
  )

  it('keeps spaces as %20 instead of stripping them', () => {
    expect(safeHref('https://example.org/a b')).toBe('https://example.org/a%20b')
  })

  it('returns the parsed href the browser will follow', () => {
    expect(safeHref('HTTPS://Example.ORG/x')).toBe('https://example.org/x')
  })

  it.each(['https://app.example@evil.com/', 'https://user:pass@example.org/', 'https://:pass@example.org/'])('rejects embedded credentials in %s', (url) => {
    expect(safeHref(url)).toBeUndefined()
  })

  it('rejects empty input', () => {
    expect(safeHref('')).toBeUndefined()
    expect(safeHref(null)).toBeUndefined()
  })
})

describe('safeRedirect', () => {
  it.each(['//evil.com', '/\\evil.com', '/\t/evil.com', '\\\\evil.com', 'https://evil.com', 'javascript:x', '', 'samples', '/login', '/login?redirect=/x'])(
    'falls back for %j',
    (raw) => {
      expect(safeRedirect(raw)).toBe('/')
    },
  )

  // Each of these resolves on our origin, but normalises to //evil.com: the output check.
  it.each(['/..//evil.com', '/.//evil.com', '/a/..//evil.com', '/%2e%2e//evil.com', '/./\\evil.com', '/.\t.//evil.com', '/.\n.//evil.com'])(
    'falls back for %j, whose normalised path is protocol-relative',
    (raw) => {
      expect(safeRedirect(raw)).toBe('/')
    },
  )

  // Decided: an encoded slash or backslash in the path falls back. No route has one, and a
  // layer that decodes it would see //evil.com. In the query it stays (a search value).
  it.each(['/%2F/evil.com', '/%2f/evil.com', '/%5C/evil.com', '/labs%2F..%2F..%2F/evil.com'])('falls back for an encoded slash in %j', (raw) => {
    expect(safeRedirect(raw)).toBe('/')
  })

  it('keeps an encoded slash in the query', () => {
    expect(safeRedirect('/labs?q=a%2Fb')).toBe('/labs?q=a%2Fb')
  })

  it.each(['/login/../login', '/login/', '/LOGIN', '/%6Cogin', '/x/../login?signedOut=true'])('never returns to the login page: %j', (raw) => {
    expect(safeRedirect(raw)).toBe('/')
  })

  it('falls back for a malformed escape in the path', () => {
    expect(safeRedirect('/labs%E0%A4%A')).toBe('/')
  })

  // The URL parser drops tabs and newlines inside the path, as browsers do.
  it.each([
    ['/la\tbs', '/labs'],
    ['/la\nbs?page=2', '/labs?page=2'],
  ])('returns %j as the parsed path %j', (raw, path) => {
    expect(safeRedirect(raw)).toBe(path)
  })

  it.each([undefined, null, 42, {}])('falls back for non-strings (%j)', (raw) => {
    expect(safeRedirect(raw)).toBe('/')
  })

  it('keeps a same-origin path with query and hash', () => {
    expect(safeRedirect('/a?b#c')).toBe('/a?b#c')
    expect(safeRedirect('/samples?page=2')).toBe('/samples?page=2')
    expect(safeRedirect('/labs/00000000-0000-4000-8000-00000000000a?offset=25')).toBe('/labs/00000000-0000-4000-8000-00000000000a?offset=25')
  })

  it('normalises dot segments that stay on a path', () => {
    expect(safeRedirect('/a/../labs')).toBe('/labs')
  })

  it('uses the given fallback', () => {
    expect(safeRedirect('//evil.com', '/home')).toBe('/home')
    expect(safeRedirect('/..//evil.com', '/home')).toBe('/home')
  })
})
