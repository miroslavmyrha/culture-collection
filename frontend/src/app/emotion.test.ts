import { afterEach, describe, expect, it } from 'vitest'
import { createEmotionCache, cspNonce } from './emotion'

function addNonceMeta(nonce: string) {
  const meta = document.createElement('meta')
  meta.setAttribute('property', 'csp-nonce')
  meta.nonce = nonce
  document.head.append(meta)
}

afterEach(() => {
  for (const meta of document.head.querySelectorAll('meta[property="csp-nonce"]')) meta.remove()
})

describe('emotion cache', () => {
  it('carries the nonce from the csp-nonce meta, so the production CSP lets MUI styles in', () => {
    addNonceMeta('r4nd0m')
    expect(cspNonce()).toBe('r4nd0m')
    expect(createEmotionCache().sheet.nonce).toBe('r4nd0m')
  })

  // Browsers hide the nonce attribute under a CSP header, jsdom does not: the e2e test proves the
  // property path in Chromium ("MUI styles apply under the production CSP").

  it('has no nonce when the page has no meta (unit tests, a page without the CSP)', () => {
    expect(cspNonce()).toBeUndefined()
    expect(createEmotionCache().sheet.nonce).toBeUndefined()
  })

  it('prepends its styles so our own CSS wins at equal specificity', () => {
    expect(createEmotionCache().sheet.prepend).toBe(true)
  })
})
