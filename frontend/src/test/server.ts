import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { problem } from './factories'

// Default handlers describe the anonymous state; tests override per case (mockApi).
export const handlers = [
  // 401 for anonymous requests; useMe also accepts the 403 older backends sent.
  http.get('*/api/v1/auth/me/', () => HttpResponse.json(problem(401, { code: 'not_authenticated' }), { status: 401 })),
  http.get('*/api/v1/auth/csrf/', () => {
    document.cookie = 'csrftoken=test-token'
    return new HttpResponse(null, { status: 204 })
  }),
  // The lab picker in the top bar asks for the user's labs on every page: no labs unless a test says.
  http.get('*/api/v1/labs/', () => HttpResponse.json({ count: 0, next: null, previous: null, results: [] })),
  // Home and the lab tabs read what waits: nothing, unless a test says.
  http.get('*/api/v1/me/overview/', () => HttpResponse.json({ waiting: [], labs: [] })),
  http.get('*/api/v1/me/activity/', () => HttpResponse.json({ results: [] })),
]

export const server = setupServer(...handlers)
