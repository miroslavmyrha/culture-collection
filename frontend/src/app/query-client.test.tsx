import { useMutation } from '@tanstack/react-query'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { api, ApiError, unwrap } from '@/lib/api'
import { problem } from '@/test/factories'
import { mockApiError } from '@/test/mockApi'
import { renderWithProviders } from '@/test/render'
import { reported } from '@/test/reports'
import { makeQueryClient } from './query-client'

function SaveButton({ handlesError = false, errorMessage }: { handlesError?: boolean; errorMessage?: string }) {
  const save = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/auth/logout/')),
    meta: { handlesError, errorMessage },
  })
  return (
    <>
      <button type="button" onClick={() => save.mutate()}>
        Save
      </button>
      {handlesError && save.isError && <p>Inline: could not save.</p>}
    </>
  )
}

async function clickSave(handlesError?: boolean, errorMessage?: string) {
  await renderWithProviders(<SaveButton handlesError={handlesError} errorMessage={errorMessage} />)
  await userEvent.setup().click(screen.getByRole('button', { name: 'Save' }))
}

describe('global mutation error message', () => {
  it('shows a safe message for a failed plain mutation and reports 5xx with the request id', async () => {
    mockApiError('post', '/api/v1/auth/logout/', 500, { detail: 'Traceback (most recent call last)' }, { headers: { 'X-Request-ID': 'req-9' } })
    await clickSave()
    expect(await screen.findByRole('alert')).toHaveTextContent('The server failed. Try again in a moment.')
    expect(screen.queryByText(/Traceback/)).not.toBeInTheDocument()
    expect(reported).toEqual([{ error: expect.any(ApiError), context: { source: 'mutation', requestId: 'req-9' } }])
  })

  it('stays quiet when the mutation handles its error (meta.handlesError)', async () => {
    mockApiError('post', '/api/v1/auth/logout/', 403, problem(403))
    await clickSave(true)
    expect(await screen.findByText('Inline: could not save.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(reported).toEqual([]) // a 403 is an answer, not a bug
  })

  it('shows the mutation\'s own message instead of the generic one (meta.errorMessage)', async () => {
    mockApiError('post', '/api/v1/auth/logout/', 500)
    await clickSave(false, 'Saving the box failed. Nothing was changed.')
    expect(await screen.findByRole('alert')).toHaveTextContent('Saving the box failed. Nothing was changed.')
    expect(screen.queryByText('The server failed. Try again in a moment.')).not.toBeInTheDocument()
  })

  it('can be dismissed', async () => {
    mockApiError('post', '/api/v1/auth/logout/', 403, problem(403))
    await clickSave()
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Dismiss' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('401 routing', () => {
  it('hands 401 from queries and mutations to onUnauthorized, without a message', async () => {
    const onUnauthorized = vi.fn<() => void>()
    const client = makeQueryClient({ onUnauthorized })
    mockApiError('get', '/api/v1/auth/csrf/', 401, problem(401))
    mockApiError('post', '/api/v1/auth/logout/', 401, problem(401))
    await client.fetchQuery({ queryKey: ['h'], queryFn: () => unwrap(api.GET('/api/v1/auth/csrf/')) }).catch(() => undefined)
    await client
      .getMutationCache()
      .build(client, { mutationFn: () => unwrap(api.POST('/api/v1/auth/logout/')) })
      .execute(undefined)
      .catch(() => undefined)
    expect(onUnauthorized).toHaveBeenCalledTimes(2)
    expect(reported).toEqual([])
  })
})
