import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { Field } from '@/components/Field'
import { isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { useLogin } from '../api/mutations'
import { type LoginInput, loginSchema } from '../schemas'

type Props = { onSuccess: () => void }

export function LoginForm({ onSuccess }: Props) {
  const login = useLogin()
  const { register, handleSubmit, formState, setError } = useForm<LoginInput>({
    resolver: zodResolver(loginSchema),
    defaultValues: { username: '', password: '' },
  })
  const onSubmit = handleSubmit((values) =>
    login.mutate(values, { onSuccess, onError: (error) => applyServerErrors(error, ['username', 'password'], setError) }),
  )
  const { username, password } = formState.errors
  // Format errors from the server go on their field. Anything else from a 400 (or 401) stays
  // generic on purpose, and root.server text is never shown: do not say which of the two was wrong.
  const rejected = isApiError(login.error, 400) || isApiError(login.error, 401)
  const invalid = rejected && username?.type !== 'server' && password?.type !== 'server'
  const failed = login.isError && !rejected
  const throttled = isApiError(login.error, 429)

  return (
    <form onSubmit={onSubmit} noValidate aria-label="Sign in">
      <Field label="Username" error={username?.message}>
        {(control) => <input autoComplete="username" {...control} {...register('username')} />}
      </Field>
      <Field label="Password" error={password?.message}>
        {(control) => <input type="password" autoComplete="current-password" {...control} {...register('password')} />}
      </Field>
      {invalid && <p role="alert">Invalid username or password.</p>}
      {/* Every other failure (CSRF 403, throttling 429, 5xx, network) must be visible too. */}
      {failed && <p role="alert">{throttled ? 'Too many attempts. Wait a minute and try again.' : 'Sign-in failed. Try again.'}</p>}
      <button type="submit" disabled={login.isPending}>
        Sign in
      </button>
    </form>
  )
}
