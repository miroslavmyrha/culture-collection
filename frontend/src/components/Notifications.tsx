import { notify, useNotices } from '@/lib/notify'

/** Renders the global error messages. Nothing is rendered while there are none. */
export function Notifications() {
  const notices = useNotices()
  if (notices.length === 0) return null
  return (
    <div role="alert" className="notifications">
      {notices.map((notice) => (
        <p key={notice.id}>
          {notice.message}{' '}
          <button type="button" onClick={() => notify.dismiss(notice.id)}>
            Dismiss
          </button>
        </p>
      ))}
    </div>
  )
}
