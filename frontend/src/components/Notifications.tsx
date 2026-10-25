import { Alert } from '@/components/ui'
import { notify, useNotices } from '@/lib/notify'
import { useFocusReturnOnUnmount } from '@/lib/focus'

/**
 * Renders the global error messages, in the shell under the bar. Nothing is rendered while
 * there are none: an empty live region on every page would be an empty alert for a screen reader.
 */
export function Notifications() {
  const notices = useNotices()
  if (notices.length === 0) return null
  return <NoticeList notices={notices} />
}

function NoticeList({ notices }: { notices: ReturnType<typeof useNotices> }) {
  // The last notice takes its close button with it: focus then goes to the page's h1.
  const remember = useFocusReturnOnUnmount()
  return (
    <div role="alert">
      {notices.map((notice) => (
        <Alert
          key={notice.id}
          severity="error"
          square
          role="none"
          closeText="Dismiss"
          data-notice=""
          onClose={(event) => {
            const button = event.currentTarget
            if (!(button instanceof HTMLElement)) return
            remember(button)
            // Another notice left: focus its close button, the one on this notice is about to go.
            const item = button.closest('[data-notice]')
            const other = item?.previousElementSibling ?? item?.nextElementSibling
            other?.querySelector<HTMLElement>('button')?.focus()
            notify.dismiss(notice.id)
          }}
        >
          {notice.message}
        </Alert>
      ))}
    </div>
  )
}
