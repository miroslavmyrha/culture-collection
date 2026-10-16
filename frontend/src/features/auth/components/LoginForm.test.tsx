import type { QueryClient } from '@tanstack/react-query'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { makeMe, problem, validationProblem } from '@/test/factories'
import { mockApi, mockApiError, recordRequests } from '@/test/mockApi'
import { makeTestQueryClient, renderWithProviders } from '@/test/render'
import { server } from '@/test/server'
import { authKeys } from '../api/keys'
import { LoginForm } from './LoginForm'

async function submit({ username = 'lab-tech', password = 'secret', client }: { username?: string; password?: string; client?: QueryClient } = {}) {
  const onSuccess = vi.fn<() => void>()
  const view = await renderWithProviders(<LoginForm onSuccess={onSuccess} />, { client })
  const user = userEvent.setup()
  if (username) await user.type(screen.getByRole('textbox', { name: 'Username' }), username)
  if (password) await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
  return { ...view, onSuccess, user }
}

describe('LoginForm', () => {
  it('stores the user in a fresh cache and calls onSuccess', async () => {
    const me = makeMe({ username: 'lab-tech' })
    mockApi('post', '/api/v1/auth/login/', me, { status: 200 })
    const client = makeTestQueryClient()
    client.setQueryData(['private', 'records'], ['earlier user'])
    const { onSuccess } = await submit({ client })
    await vi.waitFor(() => expect(onSuccess).toHaveBeenCalledOnce())
    expect(client.getQueryData(authKeys.me())).toEqual(me)
    expect(client.getQueryData(['private', 'records'])).toBeUndefined()
  })

  it.each([
    ['DRF shape', 400, { non_field_errors: ['Unable to log in with provided credentials.'] }],
    ['problem details', 400, validationProblem([{ attr: 'non_field_errors', code: 'invalid_credentials', detail: 'Invalid credentials.' }])],
    ['401', 401, problem(401)],
  ])('keeps wrong credentials generic (%s) and never shows the server text', async (_name, status, body) => {
    mockApiError('post', '/api/v1/auth/login/', status, body)
    await submit()
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password.')
    expect(screen.queryByText(/credentials/)).not.toBeInTheDocument()
  })

  it('puts a server format error on its field, linked and focused', async () => {
    mockApiError('post', '/api/v1/auth/login/', 400, validationProblem([{ attr: 'username', code: 'max_length', detail: 'Too long.' }]))
    await submit()
    const username = screen.getByRole('textbox', { name: 'Username' })
    await vi.waitFor(() => expect(username).toHaveAccessibleDescription('Too long.'))
    expect(username).toHaveAttribute('aria-invalid', 'true')
    expect(username).toHaveFocus()
    expect(screen.queryByText('Invalid username or password.')).not.toBeInTheDocument()
  })

  it.each([
    [429, 'Too many attempts. Wait a minute and try again.'],
    [403, 'Sign-in failed. Try again.'],
    [500, 'Sign-in failed. Try again.'],
  ])('shows a visible error for %i', async (status, message) => {
    mockApiError('post', '/api/v1/auth/login/', status, problem(status))
    await submit()
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(screen.getAllByRole('alert')).toHaveLength(1) // no second, global message
  })

  it('shows a visible error when offline', async () => {
    server.use(http.post('*/api/v1/auth/login/', () => HttpResponse.error()))
    await submit()
    expect(await screen.findByRole('alert')).toHaveTextContent('Sign-in failed. Try again.')
  })

  it('validates empty fields without calling the API', async () => {
    const calls = recordRequests('post', '/api/v1/auth/login/')
    await submit({ username: '', password: '' })
    expect(await screen.findByText('Enter your username')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Username' })).toHaveAccessibleDescription('Enter your username')
    expect(screen.getByRole('textbox', { name: 'Username' })).toHaveFocus()
    expect(calls).toHaveLength(0)
  })
})
