import { ConfirmDialog } from '@/components/ui'
import { useRemoveMember } from '../api/mutations'
import type { Member } from '../schemas'
import { memberError } from './memberErrors'

type Props = { labId: string; labName: string; member: Member; open: boolean; onClose: () => void; onExited: () => void }

/** A confirmation before removing. It stays open until the removal ends, and shows why it failed. */
export function RemoveMemberDialog({ labId, labName, member, open, onClose, onExited }: Props) {
  const remove = useRemoveMember(labId)
  return (
    <ConfirmDialog
      open={open}
      destructive
      title={`Remove ${member.username}?`}
      description={`${member.username} leaves ${labName} and loses access to it at once.`}
      confirmLabel="Remove"
      pending={remove.isPending}
      error={remove.isError ? memberError(remove.error) : undefined}
      onConfirm={() => remove.mutate(member.public_id, { onSuccess: onClose })}
      onClose={onClose}
      onExited={onExited}
    />
  )
}
