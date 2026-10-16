import { describe, expect, it } from 'vitest'
import { safeHref, safeRedirect } from './safe'

describe('safeHref', () => {
  it.each(['https://example.org/a', 'http://example.org', 'mailto:lab@example.org', '/relative'])('allows %s', (url) => {
    expect(safeHref(url)).toBeDefined()
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

  it.each(['https://app.example@evil.com/', 'https://user:pass@example.org/'])('rejects embedded credentials in %s', (url) => {
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

  it.each([undefined, null, 42, {}])('falls back for non-strings (%j)', (raw) => {
    expect(safeRedirect(raw)).toBe('/')
  })

  it('keeps a same-origin path with query and hash', () => {
    expect(safeRedirect('/a?b#c')).toBe('/a?b#c')
    expect(safeRedirect('/samples?page=2')).toBe('/samples?page=2')
  })

  it('uses the given fallback', () => {
    expect(safeRedirect('//evil.com', '/home')).toBe('/home')
  })
})
