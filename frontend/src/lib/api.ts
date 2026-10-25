import createClient, { type Middleware } from 'openapi-fetch'
import type { paths } from '@/api/schema'

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
const NETWORK_MESSAGE = 'Cannot reach the server. Check your connection and try again.'

export function readCookie(name: string): string | undefined {
  return document.cookie
    .split('; ')
    .find((c) => c.startsWith(`${name}=`))
    ?.slice(name.length + 1)
}

/** Production uses the __Host- prefixed cookie (Secure, no Domain, path /), development the plain one. */
export function csrfToken(): string | undefined {
  return readCookie('__Host-csrftoken') ?? readCookie('csrftoken')
}

/** One entry of a problem-details `errors` list. `attr` is the field path, null for the whole form. */
export type ProblemError = { attr: string | null; code: string; detail: string }
/** The backend's 4xx shape. Every key is optional because older endpoints may send DRF's own shapes. */
export type Problem = {
  type?: string
  title?: string
  status?: number
  detail?: string
  code?: string
  errors?: ProblemError[]
}

const isObject = (value: unknown): value is object => typeof value === 'object' && value !== null
const str = (value: unknown) => (typeof value === 'string' ? value : undefined)

/** Reads a problem-details body without trusting it. Returns undefined for any other shape. */
export function readProblem(body: unknown): Problem | undefined {
  if (!isObject(body)) return undefined
  const rawErrors: unknown = Reflect.get(body, 'errors')
  const errors = Array.isArray(rawErrors)
    ? rawErrors.flatMap((e: unknown): ProblemError[] => {
        if (!isObject(e)) return []
        const detail = str(Reflect.get(e, 'detail'))
        if (detail === undefined) return []
        return [{ attr: str(Reflect.get(e, 'attr')) ?? null, code: str(Reflect.get(e, 'code')) ?? '', detail }]
      })
    : undefined
  const problem: Problem = {
    type: str(Reflect.get(body, 'type')),
    title: str(Reflect.get(body, 'title')),
    detail: str(Reflect.get(body, 'detail')),
    code: str(Reflect.get(body, 'code')),
    errors,
  }
  const status: unknown = Reflect.get(body, 'status')
  if (typeof status === 'number') problem.status = status
  return problem.type ?? problem.title ?? problem.code ?? problem.errors ? problem : undefined
}

/** Parses Retry-After (seconds or an HTTP date) into milliseconds. */
export function parseRetryAfter(value: string | null, now = Date.now()): number | undefined {
  if (!value) return undefined
  if (/^\d+$/.test(value.trim())) return Number(value.trim()) * 1000
  const date = Date.parse(value)
  return Number.isNaN(date) ? undefined : Math.max(0, date - now)
}

type ApiErrorOptions = { requestId?: string; retryAfterMs?: number; cause?: unknown }

/**
 * Every failed API call becomes this. status 0 means the request never got a response (offline,
 * DNS, CORS). The body is kept for form mapping; never log it, it may contain user input.
 */
export class ApiError extends Error {
  readonly status: number
  readonly body: unknown
  readonly requestId: string | undefined
  readonly retryAfterMs: number | undefined
  readonly code: string | undefined

  // No parameter properties: the template enables erasableSyntaxOnly.
  constructor(status: number, body: unknown, options: ApiErrorOptions = {}) {
    super(status === 0 ? NETWORK_MESSAGE : `API error ${status}`, { cause: options.cause })
    this.name = 'ApiError'
    this.status = status
    this.body = body
    this.requestId = options.requestId
    this.retryAfterMs = options.retryAfterMs
    this.code = readProblem(body)?.code
  }
}

export const isApiError = (error: unknown, status?: number): error is ApiError =>
  error instanceof ApiError && (status === undefined || error.status === status)

const isAbort = (error: unknown) => error instanceof DOMException && error.name === 'AbortError'

/** fetch rejects with a bare TypeError ("Failed to fetch") when there is no response at all. */
function toNetworkError(error: unknown): unknown {
  return error instanceof TypeError ? new ApiError(0, undefined, { cause: error }) : error
}

// Session auth: the browser sends the HttpOnly session cookie; unsafe requests
// carry the CSRF token from the readable CSRF cookie (see csrfToken).
const csrf: Middleware = {
  onRequest({ request }) {
    if (UNSAFE.has(request.method)) {
      const token = csrfToken()
      if (token) request.headers.set('X-CSRFToken', decodeURIComponent(token))
    }
    return request
  },
}

// Absolute same-origin base: browsers resolve relative URLs, Node's fetch in tests does not.
// fetch is looked up per call, not captured at import time, so test mocks (MSW) and
// polyfills installed later are used instead of the original global.
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  credentials: 'same-origin',
  fetch: async (request) => {
    try {
      return await globalThis.fetch(request)
    } catch (error) {
      throw isAbort(error) ? error : toNetworkError(error)
    }
  },
})
api.use(csrf)

type Result<T> = { data?: T; error?: unknown; response: Response }

/**
 * The single place that turns an openapi-fetch result into data or an ApiError.
 * Checks response.ok, not only `error`: it holds even for statuses the schema does not list.
 * A 204 resolves to undefined, so only use it with operations whose data type allows that.
 */
export async function unwrap<T>(request: Promise<Result<T>> | Result<T>): Promise<T> {
  let result: Result<T>
  try {
    result = await request
  } catch (error) {
    throw toNetworkError(error)
  }
  const { data, error, response } = result
  if (response.ok && data !== undefined) return data
  // openapi-fetch already types a body-less 204 as undefined, so T includes it there.
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- a 204 has no body, and callers of a body-less endpoint ask for undefined
  if (response.status === 204) return undefined as T
  // An empty error body arrives as '' from openapi-fetch; a proxy may send an HTML page.
  throw new ApiError(response.status, error === '' ? undefined : error, {
    requestId: response.headers.get('X-Request-ID') ?? undefined,
    retryAfterMs: parseRetryAfter(response.headers.get('Retry-After')),
  })
}

/**
 * Asks for the CSRF cookie before the first unsafe request when there is none. A failed ask
 * stops the write with its own error (an ApiError, or status 0 without a response), so the form
 * says what failed instead of a 403 for a write sent without a token.
 */
export async function ensureCsrf(): Promise<void> {
  if (!csrfToken()) await unwrap(api.GET('/api/v1/auth/csrf/'))
}

const MAX_RETRIES = 2
const RETRY_STATUSES = new Set([0, 408, 429])

/** Retry only what can succeed later: no response, timeouts, throttling and 5xx. At most twice. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_RETRIES || !(error instanceof ApiError)) return false
  return RETRY_STATUSES.has(error.status) || error.status >= 500
}

/** Honours Retry-After (capped at 30 s), otherwise 1 s, 2 s, ... capped at 10 s. */
export function retryDelay(failureCount: number, error: unknown): number {
  if (error instanceof ApiError && error.retryAfterMs !== undefined) return Math.min(error.retryAfterMs, 30_000)
  return Math.min(1000 * 2 ** failureCount, 10_000)
}

/** A message that is safe to show to anyone. Never the raw server text or a stack. */
export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Something went wrong. Try again.'
  if (error.status === 0) return error.message
  if (error.status === 403) return 'You do not have permission to do that.'
  if (error.status === 404) return 'It no longer exists. Reload the page.'
  if (error.status === 409) return 'Someone else changed it. Reload and try again.'
  if (error.status === 429) return 'Too many requests. Wait a moment and try again.'
  if (error.status >= 500) return 'The server failed. Try again in a moment.'
  return 'The request was rejected. Check the form and try again.'
}
