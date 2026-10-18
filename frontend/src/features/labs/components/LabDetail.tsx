import { PageTitle, Typography } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { useLab } from '../api/queries'
import { grantableRoles, type PageParams, ROLE_LABELS } from '../schemas'
import { AddMemberForm } from './AddMemberForm'
import { LoadError } from './LoadError'
import { MemberTable } from './MemberTable'

type Props = { labId: string; params: PageParams; onOffsetChange: (offset: number) => void }

/** One lab: its name, my role, its members, and for managers the controls to manage them. */
export function LabDetail({ labId, params, onOffsetChange }: Props) {
  const lab = useLab(labId)
  if (lab.isPending)
    return (
      <>
        <PageTitle>Loading the lab</PageTitle>
        <Typography>Loading the lab…</Typography>
      </>
    )
  // 404 means "not a member" as much as "does not exist": the text says both.
  if (isApiError(lab.error, 404))
    return (
      <>
        <PageTitle>Lab not found</PageTitle>
        <Typography component="h1" variant="h4" gutterBottom>
          Lab not found
        </Typography>
        <Typography>The lab does not exist, or you are not a member of it.</Typography>
      </>
    )
  if (lab.isError)
    return (
      <>
        <PageTitle>Could not load the lab</PageTitle>
        <LoadError what="the lab" error={lab.error} onRetry={() => void lab.refetch()} />
      </>
    )
  const { name, code, my_role: role } = lab.data
  const grantable = grantableRoles(role)
  return (
    <>
      <PageTitle>{name}</PageTitle>
      <Typography component="h1" variant="h4" gutterBottom>
        {name}
      </Typography>
      <Typography sx={{ mb: 3 }}>
        Code {code}. Your role: {ROLE_LABELS[role]}.
      </Typography>
      <Typography component="h2" variant="h6" gutterBottom>
        Members
      </Typography>
      <MemberTable labId={labId} labName={name} grantable={grantable} params={params} onOffsetChange={onOffsetChange} />
      {grantable.length > 0 && <AddMemberForm labId={labId} roles={grantable} />}
    </>
  )
}
