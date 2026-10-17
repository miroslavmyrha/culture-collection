import { zodResolver } from '@hookform/resolvers/zod'
import { useId } from 'react'
import { useForm } from 'react-hook-form'
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, SelectField } from '@/components/ui'
import { useChangeRole } from '../api/mutations'
import { type ChangeRoleInput, changeRoleSchema, type Member, type Role, roleOptions } from '../schemas'
import { memberError } from './memberErrors'

type Props = { labId: string; member: Member; roles: Role[]; onClose: () => void }

export function ChangeRoleDialog({ labId, member, roles, onClose }: Props) {
  const change = useChangeRole(labId)
  const formId = useId()
  const { register, handleSubmit } = useForm<ChangeRoleInput>({
    resolver: zodResolver(changeRoleSchema),
    defaultValues: { role: member.role },
  })
  const onSubmit = handleSubmit(({ role }) => {
    if (change.isPending) return
    change.mutate({ memberId: member.public_id, role }, { onSuccess: onClose })
  })
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Change the role of {member.username}</DialogTitle>
      <DialogContent>
        <DialogContentText sx={{ mb: 2 }}>The new role applies with their next request.</DialogContentText>
        <form id={formId} onSubmit={onSubmit} noValidate aria-label={`Role of ${member.username}`}>
          <SelectField label="Role" options={roleOptions(roles)} {...register('role')} />
        </form>
        {change.isError && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {memberError(change.error)}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button type="submit" form={formId} variant="contained" aria-disabled={change.isPending}>
          Save role
        </Button>
      </DialogActions>
    </Dialog>
  )
}
