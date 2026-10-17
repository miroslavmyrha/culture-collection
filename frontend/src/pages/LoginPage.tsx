import { getRouteApi, useNavigate } from '@tanstack/react-router'
import { LoginForm } from '@/features/auth/components/LoginForm'
import { safeRedirect } from '@/lib/safe'

const route = getRouteApi('/login')

export function LoginPage() {
  const { redirect } = route.useSearch()
  const navigate = useNavigate()
  return (
    <section>
      <h1>Sign in</h1>
      <LoginForm onSuccess={() => void navigate({ href: safeRedirect(redirect), replace: true })} />
    </section>
  )
}
