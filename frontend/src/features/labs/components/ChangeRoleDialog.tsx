import { zodResolver } from '@hookform/resolvers/zod'
import { useId } from 'react'
import { useForm } from 'react-hook-form'
import { ConfirmDialog, SelectField } from '@/components/ui'
import { useChangeRole } from '../api/mutations'
import { type ChangeRoleInput, changeRoleSchema, type Member, type Role, roleOptions } from '../schemas'
import { memberError } from './memberErrors'

type Props = { labId: string; member: Member; roles: Role[]; open: boolean; onClose: () => void; onExited: () => void }

/**
 * A form in a dialog: not destructive (a role can be changed back), so a plain dialog that
 * opens on the select. Like every confirmation it stays open while the request runs.
 */
export function ChangeRoleDialog({ labId, member, roles, open, onClose, onExited }: Props) {
  const change = useChangeRole(labId)
  const formId = useId()
  const { register, handleSubmit } = useForm<ChangeRoleInput>({
    resolver: zodResolver(changeRoleSchema),
    defaultValues: { role: member.role },
  })
  const onSubmit = handleSubmit(({ role }) => change.mutate({ memberId: member.public_id, role }, { onSuccess: onClose }))
  return (
    <ConfirmDialog
      open={open}
      title={`Change the role of ${member.username}`}
      description="The new role applies with their next request."
      confirmLabel="Save role"
      form={formId}
      pending={change.isPending}
      error={change.isError ? memberError(change.error) : undefined}
      onClose={onClose}
      onExited={onExited}
    >
      <form id={formId} onSubmit={onSubmit} noValidate aria-label={`Role of ${member.username}`}>
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog) */}
        <SelectField label="Role" options={roleOptions(roles)} autoFocus {...register('role')} />
      </form>
    </ConfirmDialog>
  )
}
