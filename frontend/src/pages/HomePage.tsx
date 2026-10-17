import { useLogout } from '@/features/auth/api/mutations'
import { useMe } from '@/features/auth/api/queries'

export function HomePage() {
  const me = useMe()
  const logout = useLogout()
  return (
    <section>
      <h1>Home</h1>
      {me.data && <p>Signed in as {me.data.username}</p>}
      <button type="button" onClick={() => logout.mutate()} disabled={logout.isPending}>
        Sign out
      </button>
    </section>
  )
}
