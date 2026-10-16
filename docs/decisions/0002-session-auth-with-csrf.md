# 0002 Session authentication with CSRF for the SPA

Date: 2026-10-16
Status: accepted

## Context
The SPA and the API are served from one origin (a reverse proxy in production,
the Vite proxy in development). Tokens in browser storage can be stolen by any
XSS.

Considered: JWT in localStorage (rejected: readable by XSS), access token in
memory with an httpOnly refresh cookie (good for cross-origin APIs, more
moving parts), Django session cookie (HttpOnly) plus CSRF token (chosen).

## Decision
Django sessions with `SameSite=Lax`, HttpOnly session cookie, readable CSRF
cookie sent back as `X-CSRFToken` by the API client. Anonymous writes (login)
call `enforce_csrf()` because DRF does not check CSRF there. The dev and
preview proxies keep the Host header so the CSRF origin check matches.

Anonymous API requests get 401 with `WWW-Authenticate: Session realm="api"`
(a SessionAuthentication subclass), so the SPA can tell "log in" (401) from
"not allowed" (403). In production both cookies use the `__Host-` prefix
(`__Host-sessionid`, `__Host-csrftoken`): Secure, path `/`, no domain, so a
sibling subdomain cannot set or shadow them. Development keeps the plain names
because `__Host-` cookies need HTTPS; the SPA reads either CSRF cookie name.

## Consequences
+ Nothing secret is readable by JavaScript.
- Same-origin deployment required; a separate API domain needs CORS with
  credentials and trusted origins, revisit then.

Revisit when: the API must serve other origins or mobile apps.
