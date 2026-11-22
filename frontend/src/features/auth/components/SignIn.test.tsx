import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { makeMe, problem } from '@/test/factories'
import { mockApi, mockApiError } from '@/test/mockApi'
import { makeTestQueryClient, renderWithProviders } from '@/test/render'
import { authKeys } from '../api/keys'
import { qrPath } from './QrCode'
import { SignIn } from './SignIn'

type Step = { step: 'second_factor' | 'enrol'; methods: ('security_key' | 'totp' | 'recovery_code')[] }

async function password(step: Step) {
  mockApi('post', '/api/v1/auth/login/', step, { status: 200 })
  const onSignedIn = vi.fn<(me: unknown) => void>()
  const client = makeTestQueryClient()
  await renderWithProviders(<SignIn onSignedIn={onSignedIn} />, { client })
  const user = userEvent.setup()
  await user.type(screen.getByRole('textbox', { name: 'Username' }), 'lab-tech')
  await user.type(screen.getByLabelText('Password'), 'secret')
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
  return { user, onSignedIn, client }
}

describe('SignIn', () => {
  it('asks for the code after the password and signs in with it', async () => {
    const me = makeMe({ username: 'lab-tech' })
    const calls = mockApi('post', '/api/v1/auth/second-factor/', me, { status: 200 })
    const { user, onSignedIn, client } = await password({ step: 'second_factor', methods: ['totp', 'recovery_code'] })
    await user.type(await screen.findByRole('textbox', { name: 'Code from your authenticator app' }), '123456')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await vi.waitFor(() => expect(onSignedIn).toHaveBeenCalledOnce())
    expect(calls[0]?.body).toEqual({ method: 'totp', code: '123456' })
    expect(client.getQueryData(authKeys.me())).toEqual(me)
  })

  it('takes a recovery code instead', async () => {
    const calls = mockApi('post', '/api/v1/auth/second-factor/', makeMe(), { status: 200 })
    const { user } = await password({ step: 'second_factor', methods: ['totp', 'recovery_code'] })
    await user.click(await screen.findByRole('button', { name: 'Use a recovery code instead' }))
    await user.type(screen.getByRole('textbox', { name: 'Recovery code' }), 'abcde-fghjk')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await vi.waitFor(() => expect(calls[0]?.body).toEqual({ method: 'recovery_code', code: 'abcde-fghjk' }))
  })

  it('offers the security key first when the account has one', async () => {
    await password({ step: 'second_factor', methods: ['security_key', 'recovery_code'] })
    expect(await screen.findByRole('button', { name: 'Use your security key' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Code from your authenticator app' })).not.toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Recovery code' })).toBeInTheDocument()
  })

  it('says a wrong code in the server words and stays on the step', async () => {
    mockApiError('post', '/api/v1/auth/second-factor/', 422, problem(422, { code: 'wrong_code', detail: 'The code is not valid.' }))
    const { user, onSignedIn } = await password({ step: 'second_factor', methods: ['totp'] })
    await user.type(await screen.findByRole('textbox', { name: 'Code from your authenticator app' }), '000000')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The code is not valid.')
    expect(onSignedIn).not.toHaveBeenCalled()
  })

  it('goes back to the password when the step expired', async () => {
    mockApiError('post', '/api/v1/auth/second-factor/', 401, problem(401))
    const { user } = await password({ step: 'second_factor', methods: ['totp'] })
    await user.type(await screen.findByRole('textbox', { name: 'Code from your authenticator app' }), '123456')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByText('The sign-in took too long. Sign in again.')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Username' })).toBeInTheDocument()
  })

  it('enrols an authenticator app at the first sign-in and shows the recovery codes once', async () => {
    const me = makeMe({ username: 'lab-tech' })
    mockApi('post', '/api/v1/auth/factors/totp/setup/', { secret: 'JBSWY3DPEHPK3PXP', uri: 'otpauth://totp/x?secret=JBSWY3DPEHPK3PXP' }, { status: 200 })
    const enrol = mockApi('post', '/api/v1/auth/factors/totp/', { me, recovery_codes: ['aaaaa-bbbbb', 'ccccc-ddddd'] }, { status: 201 })
    const code = mockApi('post', '/api/v1/auth/enrolment-code/', undefined, { status: 204 })
    const { user, onSignedIn } = await password({ step: 'enrol', methods: [] })
    expect(await screen.findByRole('heading', { name: 'Add a second factor' })).toBeInTheDocument()
    // The manager's code first (#176): no key or app without it.
    expect(screen.queryByRole('button', { name: 'Add a security key' })).not.toBeInTheDocument()
    await user.type(screen.getByRole('textbox', { name: 'Enrolment code' }), 'abcde-fghjk')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await vi.waitFor(() => expect(code[0]?.body).toEqual({ code: 'abcde-fghjk' }))
    await user.click(await screen.findByRole('button', { name: 'Use an authenticator app instead' }))
    await user.click(screen.getByRole('button', { name: 'Show the code for the app' }))
    expect(await screen.findByRole('img', { name: 'QR code for the authenticator app' })).toBeInTheDocument()
    expect(screen.getByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument()
    await user.type(screen.getByRole('textbox', { name: 'Code from the app' }), '654321')
    await user.click(screen.getByRole('button', { name: 'Add the app' }))
    const codes = await screen.findByRole('list', { name: 'Recovery codes' })
    expect(codes).toHaveTextContent('aaaaa-bbbbb')
    expect(enrol[0]?.body).toEqual({ code: '654321' })
    expect(onSignedIn).not.toHaveBeenCalled() // not before the codes were seen
    await user.click(screen.getByRole('button', { name: 'I have saved them, continue' }))
    expect(onSignedIn).toHaveBeenCalledWith(me)
  })
})

describe('SignIn, the enrolment code', () => {
  it('says a wrong code and does not go on', async () => {
    mockApiError('post', '/api/v1/auth/enrolment-code/', 422, problem(422, { code: 'wrong_code', detail: 'The enrolment code is not valid, used or expired.' }))
    const { user } = await password({ step: 'enrol', methods: [] })
    await user.type(await screen.findByRole('textbox', { name: 'Enrolment code' }), 'nope')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The enrolment code is not valid, used or expired.')
    expect(screen.queryByRole('button', { name: 'Add a security key' })).not.toBeInTheDocument()
  })
})

describe('qrPath', () => {
  it('draws one square per dark module, nothing for a light one', () => {
    expect(
      qrPath([
        [true, false],
        [false, true],
      ]),
    ).toBe('M0 0h1v1h-1zM1 1h1v1h-1z')
  })
})
