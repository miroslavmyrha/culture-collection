import { useBlocker } from '@tanstack/react-router'
import { type ReactElement, useRef } from 'react'
import { ConfirmDialog } from '@/components/ui'

/** The question itself; Cancel stays on the form. */
export function LeaveDialog({ open, onStay, onLeave }: { open: boolean; onStay: () => void; onLeave: () => void }) {
  return (
    <ConfirmDialog
      open={open}
      destructive
      title="Leave without saving?"
      description="What you typed on this page is lost if you leave. This cannot be undone."
      confirmLabel="Leave"
      pending={false}
      onConfirm={onLeave}
      onClose={onStay}
    />
  )
}

/**
 * Asks before a form with unsaved changes is left by a link, Back or Forward, and makes the
 * browser ask before the tab closes or reloads. Cancel stays on the form with everything typed;
 * Leave goes on to where the user was heading. Render `dialog` anywhere in the form's component.
 * Call `allowLeaving()` just before the form navigates away on purpose, after a save: the
 * dirty flag of the render that is still on screen would block that move.
 */
export function useUnsavedGuard(dirty: boolean): { dialog: ReactElement; allowLeaving: () => void } {
  const allowed = useRef(false)
  const blocker = useBlocker({
    shouldBlockFn: () => dirty && !allowed.current,
    enableBeforeUnload: () => dirty && !allowed.current,
    withResolver: true,
  })
  return {
    dialog: <LeaveDialog open={blocker.status === 'blocked'} onStay={() => blocker.reset?.()} onLeave={() => blocker.proceed?.()} />,
    allowLeaving: () => {
      allowed.current = true
    },
  }
}
