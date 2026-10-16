import DOMPurify from 'dompurify'

// An explicit allowlist: no images (remote URLs leak the reader's IP and track them), no styles,
// no forms, no frames. Links only to the protocols safeHref accepts, or relative.
const ALLOWED_TAGS = ['a', 'b', 'blockquote', 'br', 'code', 'em', 'h2', 'h3', 'h4', 'hr', 'i', 'li', 'ol', 'p', 'pre', 's', 'strong', 'table', 'tbody', 'td', 'th', 'thead', 'tr', 'ul']
const ALLOWED_ATTR = ['href', 'title', 'colspan', 'rowspan']
const ALLOWED_URI_REGEXP = /^(?:https?:|mailto:|[/#?])/i
// DOMPurify tests every allowed attribute that is not on its URI-safe list against
// ALLOWED_URI_REGEXP. Plain values such as colspan="2" must be declared URI-safe or they are dropped.
const ADD_URI_SAFE_ATTR = ['colspan', 'rowspan']

/**
 * Returns TrustedHTML where the browser enforces Trusted Types, a string elsewhere (jsdom).
 * DOMPurify creates its Trusted Types policy named "dompurify" on first use.
 * No hooks: they would be global to every caller of DOMPurify.
 */
export function sanitizeHtml(html: string): TrustedHTML | string {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS, ALLOWED_ATTR, ALLOWED_URI_REGEXP, ADD_URI_SAFE_ATTR, RETURN_TRUSTED_TYPE: true })
}

/** Called once at boot, so a policy name missing from the CSP fails at startup, not on first use. */
export function initTrustedTypes(): void {
  sanitizeHtml('')
}
