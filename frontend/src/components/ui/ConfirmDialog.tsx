import { Alert, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle } from '@mui/material'
import { type MouseEvent, type ReactNode, useId } from 'react'

type Action =
  /** The confirm button runs this. */
  | { onConfirm: () => void; form?: never }
  /** The confirm button submits this form (an id of a form among the children). */
  | { form: string; onConfirm?: never }

type Props = Action & {
  open: boolean
  title: ReactNode
  /** What the action does, in a sentence or two: the dialog's accessible description. */
  description: ReactNode
  confirmLabel: string
  /** Hard to undo (removing, losing access): an alertdialog, a red button, focus on Cancel. */
  destructive?: boolean
  /** The action runs: nothing closes the dialog and confirm does not run again. */
  pending: boolean
  /** Why the action failed. Shown inside the dialog, which stays open. */
  error?: string
  onClose: () => void
  /** Fields between the description and the error (a form for `form`). */
  children?: ReactNode
}

/**
 * A confirmation that stays open while its action runs. Closing it then would unmount the
 * component that owns the mutation, and a failure that the dialog was meant to show (the
 * mutation has meta.handlesError) would be shown nowhere. So while pending, Escape and the
 * backdrop are ignored and Cancel and confirm do nothing. Both stay focusable (aria-disabled
 * and a guard, not disabled, which drops the focus to the body). MUI's Button `loading` sets
 * disabled (@mui/material 9.5.0, Button/Button.js:582), so confirm shows its own spinner.
 * MUI labels the dialog by its DialogTitle but does not describe it: the description and the
 * error are wired here.
 */
export function ConfirmDialog({ open, title, description, confirmLabel, destructive = false, pending, error, onClose, children, ...action }: Props) {
  const descriptionId = useId()
  const errorId = useId()
  const close = () => {
    if (!pending) onClose()
  }
  const confirm = (event: MouseEvent<HTMLButtonElement>) => {
    if (pending) {
      event.preventDefault() // also stops the submit of a form
      return
    }
    action.onConfirm?.()
  }
  return (
    <Dialog
      open={open}
      onClose={close}
      fullWidth
      maxWidth="xs"
      role={destructive ? 'alertdialog' : 'dialog'}
      aria-describedby={error ? `${descriptionId} ${errorId}` : descriptionId}
    >
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <DialogContentText id={descriptionId}>{description}</DialogContentText>
        {children}
        {error && (
          <Alert id={errorId} severity="error" sx={{ mt: 2 }}>
            {error}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a destructive confirmation opens on the least destructive action (WAI-ARIA alertdialog) */}
        <Button onClick={close} aria-disabled={pending} autoFocus={destructive}>
          Cancel
        </Button>
        <Button
          type={action.form ? 'submit' : 'button'}
          form={action.form}
          variant="contained"
          color={destructive ? 'error' : 'primary'}
          onClick={confirm}
          aria-disabled={pending}
          aria-busy={pending}
          startIcon={pending ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined}
        >
          {confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
