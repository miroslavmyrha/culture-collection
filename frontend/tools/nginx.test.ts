import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { CSP_NONCE, securityHeaders } from '../vite.config.ts'

// The production proxy (#178) sends the policy of vite.config.ts, written a second time in nginx
// syntax: these tests keep the two copies equal.
const nginx = join(resolve(import.meta.dirname, '..'), 'nginx')
const NGINX_NONCE = '$request_id'
const read = (path: string) => readFileSync(join(nginx, path), 'utf8')

/** The add_header lines of a snippet, by header name. */
export function addedHeaders(text: string): Record<string, string> {
  const headers: Record<string, string> = {}
  for (const [, name = '', value = ''] of text.matchAll(/^add_header (\S+) "([^"]*)" always;$/gm)) headers[name] = value
  return headers
}

describe('the proxy configuration', () => {
  it('sends the security headers of vite.config.ts with the nonce of the response, and HSTS', () => {
    const expected = Object.fromEntries(Object.entries(securityHeaders).map(([name, value]: [string, string]) => [name, value.replaceAll(CSP_NONCE, NGINX_NONCE)]))
    expect(addedHeaders(read('snippets/spa-headers.conf'))).toEqual({ ...expected, 'Strict-Transport-Security': 'max-age=31536000; includeSubDomains' })
  })

  it('replaces the placeholder Vite stamps with the same nonce in the page', () => {
    expect(read('default.conf.template')).toContain(`sub_filter "${CSP_NONCE}" "${NGINX_NONCE}";`)
  })

  it('reads a changed header as a difference', () => {
    // The parser must see every line, or the first test would pass on an empty file.
    expect(addedHeaders('add_header X-Frame-Options "SAMEORIGIN" always;\n')).toEqual({ 'X-Frame-Options': 'SAMEORIGIN' })
    expect(addedHeaders(read('snippets/spa-headers.conf'))['X-Frame-Options']).not.toBe('SAMEORIGIN')
  })

  it('includes the headers in every location that serves the SPA', () => {
    // The HTTPS server only: the HTTP one redirects.
    const template = read('default.conf.template').split('listen 8443 ssl;')[1] ?? ''
    const spa = ['location /assets/', 'location / ', 'location = /index.html']
    for (const location of spa) {
      const block = template.slice(template.indexOf(location), template.indexOf('}', template.indexOf(location)))
      expect(`${location}: ${block}`).toContain('include /etc/nginx/snippets/spa-headers.conf;')
    }
  })
})
