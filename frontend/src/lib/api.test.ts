import { http, HttpResponse } from 'msw'
import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { makeMe, problem } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { server } from '@/test/server'
import { api, ApiError, csrfToken, errorMessage, parseRetryAfter, readProblem, retryDelay, shouldRetry, unwrap } from './api'

const getMe = () => unwrap(api.GET('/api/v1/auth/me/'))

describe('unwrap', () => {
  it('returns the data of a 2xx', async () => {
    const me = makeMe()
    mockApi('get', '/api/v1/auth/me/', me)
    await expect(getMe()).resolves.toEqual(me)
  })

  it('resolves a 204 to undefined', async () => {
    mockApi('post', '/api/v1/auth/logout/', undefined)
    await expect(unwrap(api.POST('/api/v1/auth/logout/'))).resolves.toBeUndefined()
  })

  it('throws an ApiError with status, body, request id and Retry-After', async () => {
    const body = problem(429, { code: 'throttled' })
    mockApiError('get', '/api/v1/auth/me/', 429, body, { headers: { 'X-Request-ID': 'req-1', 'Retry-After': '7' } })
    const error = await getMe().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 429, body, requestId: 'req-1', retryAfterMs: 7000, code: 'throttled', name: 'ApiError' })
  })

  it('throws for an error status the schema does not list, even without a body', async () => {
    mockApiError('get', '/api/v1/auth/me/', 502)
    await expect(getMe()).rejects.toMatchObject({ status: 502, body: undefined })
  })

  it('turns a network failure into a readable ApiError with status 0', async () => {
    server.use(http.get('*/api/v1/auth/me/', () => HttpResponse.error()))
    const error = await getMe().catch((e: unknown) => e)
    expect(error).toMatchObject({ status: 0, message: 'Cannot reach the server. Check your connection and try again.' })
    expect(error).toHaveProperty('cause', expect.any(TypeError))
  })

  it('maps a TypeError from a pre-awaited call too', async () => {
    await expect(unwrap(Promise.reject(new TypeError('Failed to fetch')))).rejects.toMatchObject({ status: 0 })
  })

  it('lets aborts through untouched', async () => {
    mockApi('get', '/api/v1/auth/me/', makeMe())
    const controller = new AbortController()
    controller.abort()
    const error = await unwrap(api.GET('/api/v1/auth/me/', { signal: controller.signal })).catch((e: unknown) => e)
    expect(error).not.toBeInstanceOf(ApiError)
    expect(error).toHaveProperty('name', 'AbortError')
  })
})

describe('readProblem', () => {
  it('reads problem details and drops malformed entries', () => {
    expect(
      readProblem({ type: 't', status: 400, code: 'invalid', errors: [{ attr: 'name', code: 'blank', detail: 'Required.' }, { attr: 'x' }, 'junk'] }),
    ).toEqual({ type: 't', title: undefined, detail: undefined, status: 400, code: 'invalid', errors: [{ attr: 'name', code: 'blank', detail: 'Required.' }] })
  })

  it.each([null, 'text', ['a'], { name: ['Required.'] }, { detail: 'only DRF detail' }])('returns undefined for %j', (body) => {
    expect(readProblem(body)).toBeUndefined()
  })
})

// The same defaults app/query-client.ts sets (shared code does not import the app).
const makeQueryClient = () => new QueryClient({ defaultOptions: { queries: { retry: shouldRetry, retryDelay } } })

const err = (status: number) => new ApiError(status, undefined)

describe('retry policy', () => {
  it.each([0, 408, 429, 500, 503])('retries %i', (status) => {
    expect(shouldRetry(0, err(status))).toBe(true)
  })

  it.each([400, 401, 403, 404, 409, 422])('never retries %i', (status) => {
    expect(shouldRetry(0, err(status))).toBe(false)
  })

  it('stops after two retries and never retries non-API errors', () => {
    expect(shouldRetry(1, err(503))).toBe(true)
    expect(shouldRetry(2, err(503))).toBe(false)
    expect(shouldRetry(0, new Error('bug'))).toBe(false)
  })

  it('honours Retry-After, capped, otherwise backs off exponentially', () => {
    expect(retryDelay(0, new ApiError(429, undefined, { retryAfterMs: 5000 }))).toBe(5000)
    expect(retryDelay(0, new ApiError(429, undefined, { retryAfterMs: 999_000 }))).toBe(30_000)
    expect([0, 1, 2, 5].map((n) => retryDelay(n, err(503)))).toEqual([1000, 2000, 4000, 10_000])
  })

  it('parses Retry-After seconds and dates', () => {
    expect(parseRetryAfter('3')).toBe(3000)
    expect(parseRetryAfter('Thu, 01 Jan 1970 00:00:10 GMT', 4000)).toBe(6000)
    expect(parseRetryAfter('soon')).toBeUndefined()
    expect(parseRetryAfter(null)).toBeUndefined()
  })

  it('makes exactly one call for a 404', async () => {
    const calls = mockApiError('get', '/api/v1/auth/me/', 404, problem(404))
    await makeQueryClient().fetchQuery({ queryKey: ['me'], queryFn: getMe }).catch(() => undefined)
    expect(calls).toHaveLength(1)
  })

  it('retries 503, 503, then succeeds on the third call (Retry-After: 0)', async () => {
    const me = makeMe()
    let calls = 0
    server.use(
      http.get('*/api/v1/auth/me/', () =>
        ++calls <= 2 ? HttpResponse.json(problem(503), { status: 503, headers: { 'Retry-After': '0' } }) : HttpResponse.json(me),
      ),
    )
    await expect(makeQueryClient().fetchQuery({ queryKey: ['me'], queryFn: getMe })).resolves.toEqual(me)
    expect(calls).toBe(3)
  })
})

describe('errorMessage', () => {
  it.each([
    [0, 'Cannot reach the server. Check your connection and try again.'],
    [403, 'You do not have permission to do that.'],
    [429, 'Too many requests. Wait a moment and try again.'],
    [500, 'The server failed. Try again in a moment.'],
  ])('maps %i to a safe message', (status, message) => {
    expect(errorMessage(new ApiError(status, { detail: 'internal detail' }))).toBe(message)
  })

  it('never shows a raw error', () => {
    expect(errorMessage(new Error('SELECT * FROM secrets'))).toBe('Something went wrong. Try again.')
  })
})

describe('csrfToken', () => {
  it('prefers the production __Host- cookie and falls back to the development one', () => {
    const cookie = vi.spyOn(document, 'cookie', 'get')
    cookie.mockReturnValue('csrftoken=dev; __Host-csrftoken=prod')
    expect(csrfToken()).toBe('prod')
    cookie.mockReturnValue('sessionid=x; csrftoken=dev')
    expect(csrfToken()).toBe('dev')
    cookie.mockReturnValue('')
    expect(csrfToken()).toBeUndefined()
  })
})
