import { Alert, Button, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle } from '@/components/ui'
import { useRemoveMember } from '../api/mutations'
import type { Member } from '../schemas'
import { memberError } from './memberErrors'

type Props = { labId: string; labName: string; member: Member; onClose: () => void }

/** A confirmation before removing: the least destructive button has the focus. */
export function RemoveMemberDialog({ labId, labName, member, onClose }: Props) {
  const remove = useRemoveMember(labId)
  const confirm = () => {
    if (remove.isPending) return
    remove.mutate(member.public_id, { onSuccess: onClose })
  }
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Remove {member.username}?</DialogTitle>
      <DialogContent>
        <DialogContentText>
          {member.username} leaves {labName} and loses access to it at once.
        </DialogContentText>
        {remove.isError && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {memberError(remove.error)}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a confirmation dialog opens on the least destructive action (WAI-ARIA alertdialog) */}
        <Button onClick={onClose} autoFocus>
          Cancel
        </Button>
        <Button color="error" variant="contained" onClick={confirm} aria-disabled={remove.isPending}>
          Remove
        </Button>
      </DialogActions>
    </Dialog>
  )
}
