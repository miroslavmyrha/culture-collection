import { http, HttpResponse, type HttpHandler } from 'msw'
import type { paths } from '@/api/schema'
import type { Problem } from '@/lib/api'
import { server } from './server'

type Method = 'get' | 'post' | 'put' | 'patch' | 'delete'
/** Paths that have this method in the generated schema. */
export type PathFor<M extends Method> = {
  [P in keyof paths]: [NonNullable<paths[P][M]>] extends [never] ? never : P
}[keyof paths]
type Responses<P extends keyof paths, M extends Method> = NonNullable<paths[P][M]> extends { responses: infer R } ? R : never
type Json<R> = R extends { content: { 'application/json': infer B } } ? B : undefined
/** The JSON body of the operation's 200, 201 or 204 response, straight from the schema. */
export type SuccessBody<P extends keyof paths, M extends Method> = Json<Responses<P, M>[Extract<keyof Responses<P, M>, 200 | 201 | 204>]>

export type RecordedRequest = { method: string; url: URL; headers: Headers; body: unknown }
type Init = { status?: number; headers?: Record<string, string> }

/** '/api/v1/boxes/{public_id}/' becomes '*\/api/v1/boxes/:public_id/'. */
const pattern = (path: string) => `*${path.replace(/\{(\w+)\}/g, ':$1')}`

async function record(request: Request): Promise<RecordedRequest> {
  const text = await request.clone().text()
  let body: unknown = text || undefined
  try {
    body = text ? JSON.parse(text) : undefined
  } catch {
    // not JSON: keep the text
  }
  return { method: request.method, url: new URL(request.url), headers: request.headers, body }
}

function handler(method: Method, path: string, calls: RecordedRequest[], respond: () => Response): HttpHandler {
  return http[method](pattern(path), async ({ request }) => {
    calls.push(await record(request))
    return respond()
  })
}

/**
 * Answers a schema path with a body typed from the generated schema: when the API changes,
 * tsc breaks the mock instead of the test passing on a stale shape. Returns the requests it
 * answered, so a test asserts what was sent and how often.
 */
export function mockApi<M extends Method, P extends PathFor<M>>(method: M, path: P, body: SuccessBody<P, M>, init: Init = {}) {
  const calls: RecordedRequest[] = []
  const status = init.status ?? (body === undefined ? 204 : method === 'post' ? 201 : 200)
  server.use(
    handler(method, path, calls, () =>
      body === undefined ? new HttpResponse(null, { status, headers: init.headers }) : HttpResponse.json(body, { status, headers: init.headers }),
    ),
  )
  return calls
}

/** Answers a schema path with an error status and a problem-details (or DRF) body. */
export function mockApiError<M extends Method>(
  method: M,
  path: PathFor<M>,
  status: number,
  body: Problem | Record<string, unknown> | null = null,
  init: Omit<Init, 'status'> = {},
) {
  const calls: RecordedRequest[] = []
  server.use(
    handler(method, path, calls, () =>
      body === null ? new HttpResponse(null, { status, headers: init.headers }) : HttpResponse.json(body, { status, headers: init.headers }),
    ),
  )
  return calls
}

/**
 * Records requests without answering them: the next matching handler (a default one or an
 * earlier mockApi) still responds. Register it after the mocks it should observe.
 * "No request was made" is expect(calls).toHaveLength(0) after the UI settled.
 */
export function recordRequests<M extends Method>(method: M, path: PathFor<M>) {
  const calls: RecordedRequest[] = []
  server.use(
    http[method](pattern(path), async ({ request }) => {
      calls.push(await record(request))
      // no return: fall through to the next handler
    }),
  )
  return calls
}
