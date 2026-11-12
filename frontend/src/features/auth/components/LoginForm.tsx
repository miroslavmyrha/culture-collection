import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { Alert, Button, Stack, TextField } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { useLogin } from '../api/mutations'
import { type LoginInput, loginSchema } from '../schemas'

type Props = { onSuccess: () => void }

const MINUTE_MS = 60_000

/**
 * The 429 says when to try again (Retry-After) and nothing else: an unknown name gets the same
 * answer. While an account is under attack, a browser that signed in to it before may still try.
 */
function tooManyAttempts(retryAfterMs: number | undefined): string {
  const minutes = retryAfterMs === undefined ? undefined : Math.max(1, Math.ceil(retryAfterMs / MINUTE_MS))
  const when = minutes === undefined ? 'later' : `in ${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`
  return `Too many sign-in attempts. Try again ${when}. A browser you signed in with before may still work.`
}

type FieldError = { type?: string; message?: string } | undefined

/**
 * What a failed sign-in says. Format errors from the server go on their field. Anything else from
 * a 400 (or 401) stays generic on purpose, and root.server text is never shown: do not say which
 * of the two was wrong. Every other failure (CSRF 403, throttling 429, 5xx, network) must be visible too.
 */
function LoginFailure({ error, isError, username, password }: { error: unknown; isError: boolean; username: FieldError; password: FieldError }) {
  if (isApiError(error, 400) || isApiError(error, 401)) return onField(username) || onField(password) ? null : <Alert severity="error">Invalid username or password.</Alert>
  return isError ? <Alert severity="error">{failureText(error)}</Alert> : null
}

const onField = (error: FieldError) => error?.type === 'server'

/** The 429's own words, else the general ones. */
const failureText = (error: unknown) => (isApiError(error, 429) ? tooManyAttempts(error.retryAfterMs) : 'Sign-in failed. Try again.')

export function LoginForm({ onSuccess }: Props) {
  const login = useLogin()
  const { register, handleSubmit, formState, setError } = useForm<LoginInput>({
    resolver: zodResolver(loginSchema),
    defaultValues: { username: '', password: '' },
  })
  const onSubmit = handleSubmit((values) => {
    if (login.isPending) return // aria-disabled keeps the focus on the button, so guard here
    login.mutate(values, { onSuccess, onError: (error) => applyServerErrors(error, ['username', 'password'], setError) })
  })
  const { username, password } = formState.errors

  return (
    <form onSubmit={onSubmit} noValidate aria-label="Sign in">
      <Stack spacing={2}>
        <TextField label="Username" autoComplete="username" error={username?.message} {...register('username')} />
        <TextField label="Password" type="password" autoComplete="current-password" error={password?.message} {...register('password')} />
        <LoginFailure error={login.error} isError={login.isError} username={username} password={password} />
        {/* aria-disabled, not disabled: disabling the focused button drops focus to the body, and
            after "Invalid username or password." the keyboard user starts from nowhere. */}
        <Button type="submit" variant="contained" aria-disabled={login.isPending}>
          Sign in
        </Button>
      </Stack>
    </form>
  )
}
