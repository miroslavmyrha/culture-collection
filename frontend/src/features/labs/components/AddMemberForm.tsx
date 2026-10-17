import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Alert, Box, Button, SelectField, Stack, TextField, Typography } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { useAddMember } from '../api/mutations'
import { type AddMemberInput, addMemberSchema, type Role, roleOptions } from '../schemas'

type Props = { labId: string; roles: Role[] }

/** For managers: add an existing active user by username, with a role up to the manager's own. */
export function AddMemberForm({ labId, roles }: Props) {
  const add = useAddMember(labId)
  const [failure, setFailure] = useState<string>()
  const [added, setAdded] = useState<string>()
  const { register, handleSubmit, formState, reset, setError } = useForm<AddMemberInput>({
    resolver: zodResolver(addMemberSchema),
    defaultValues: { username: '', role: 'viewer' },
  })
  const onSubmit = handleSubmit((values) => {
    if (add.isPending) return // aria-disabled keeps focus on the button, so guard here
    setFailure(undefined)
    setAdded(undefined)
    add.mutate(values, {
      onSuccess: (member) => {
        reset()
        setAdded(member.username)
      },
      // Field errors (unknown user, already a member) go on their field, focused. Anything else is one message.
      onError: (error) => {
        if (!applyServerErrors(error, ['username', 'role'], setError)) setFailure(errorMessage(error))
      },
    })
  })
  const message = formState.errors.root?.server?.message ?? failure

  return (
    <Box component="form" onSubmit={onSubmit} noValidate aria-label="Add a member" sx={{ mt: 4 }}>
      <Typography component="h2" variant="h6" gutterBottom>
        Add a member
      </Typography>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ alignItems: 'flex-start' }}>
        <TextField
          label="Username"
          autoComplete="off"
          hint="An existing, active user"
          error={formState.errors.username?.message}
          {...register('username')}
        />
        <SelectField label="Role" options={roleOptions(roles)} error={formState.errors.role?.message} {...register('role')} />
        <Button type="submit" variant="contained" aria-disabled={add.isPending} sx={{ mt: 1 }}>
          Add member
        </Button>
      </Stack>
      {message && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {message}
        </Alert>
      )}
      {added && <output>Added {added}.</output>}
    </Box>
  )
}
