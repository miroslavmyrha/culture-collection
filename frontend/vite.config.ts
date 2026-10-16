import babel from '@rolldown/plugin-babel'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Vite stamps this placeholder as nonce="" on its script and link tags and adds
// <meta property="csp-nonce">. The reverse proxy replaces it per response with a fresh
// random value and sends the same value in the CSP header (nginx: see project-setup.md).
// `vite preview` sends the placeholder itself, which is a valid nonce token, so e2e tests run
// against the same markup and policy as production.
export const CSP_NONCE = '__CSP_NONCE__'

/**
 * The production policy. script-src needs no nonce: a Vite build has no inline scripts.
 * The style nonce is for CSS-in-JS (MUI/emotion) once added. Trusted Types: only the policy
 * DOMPurify creates ("dompurify") may produce HTML for DOM sinks; there is no default policy.
 */
export function productionCsp(nonce: string) {
  return [
    "default-src 'self'",
    "script-src 'self'",
    `style-src 'self' 'nonce-${nonce}'`,
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "worker-src 'self'",
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "require-trusted-types-for 'script'",
    'trusted-types dompurify',
  ].join('; ')
}

/** Set these on every HTML response in production (proxy or CDN), with the CSP above. */
export const securityHeaders = {
  'Content-Security-Policy': productionCsp(CSP_NONCE),
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
  'Cross-Origin-Opener-Policy': 'same-origin',
  'X-Frame-Options': 'DENY', // frame-ancestors covers modern browsers; this covers old ones
}

// Keep the browser's Host header (changeOrigin: false) so Django sees the same
// origin as the browser and its CSRF origin check passes, exactly as behind a
// production reverse proxy. Vite 8 rewrote Host by default in our test.
const apiProxy = {
  '/api': { target: process.env.VITE_API_PROXY ?? 'http://localhost:8000', changeOrigin: false },
}

export default defineConfig({
  plugins: [babel({ presets: [reactCompilerPreset()] }), react()],
  resolve: { alias: { '@': new URL('./src', import.meta.url).pathname } },
  html: { cspNonce: CSP_NONCE },
  build: {
    // Maps for the error tracker, without a sourceMappingURL comment in the served files.
    // Upload them in CI, then delete dist/**/*.map before deploying.
    sourcemap: 'hidden',
    // Do not raise this for the entry chunk: split routes or dependencies instead.
    chunkSizeWarningLimit: 500,
  },
  server: {
    // Same-origin in development: the session and CSRF cookies just work.
    proxy: apiProxy,
  },
  preview: {
    proxy: apiProxy,
    headers: securityHeaders,
  },
})
