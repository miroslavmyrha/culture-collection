import createCache, { type EmotionCache } from '@emotion/cache'

/**
 * The style nonce Vite stamps on <meta property="csp-nonce"> (html.cspNonce in vite.config.ts).
 * The reverse proxy replaces the placeholder with a fresh value per response. Read the property,
 * not the attribute: once the CSP header applies, browsers hide nonce attributes.
 */
export function cspNonce(doc: Document = document): string | undefined {
  const nonce = doc.querySelector<HTMLMetaElement>('meta[property="csp-nonce"]')?.nonce
  return nonce === undefined || nonce === '' ? undefined : nonce
}

/**
 * Emotion inserts <style> elements at runtime. Without the nonce the production CSP
 * (style-src 'self' 'nonce-...') blocks every MUI style. prepend puts them before our own CSS,
 * so ours wins at equal specificity.
 */
export function createEmotionCache(doc: Document = document): EmotionCache {
  return createCache({ key: 'mui', nonce: cspNonce(doc), prepend: true })
}
