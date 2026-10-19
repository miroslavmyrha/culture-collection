import { Link, PageTitle, Typography } from '@/components/ui'
import { grantableRoles, type PageParams, ROLE_LABELS } from '../schemas'
import { AddMemberForm } from './AddMemberForm'
import { LabGate } from './LabGate'
import { MemberTable } from './MemberTable'

type Props = { labId: string; params: PageParams; onOffsetChange: (offset: number) => void }

/** One lab: its name, my role, its strains, its members, and for managers the controls to manage them. */
export function LabDetail({ labId, params, onOffsetChange }: Props) {
  return (
    <LabGate labId={labId}>
      {({ name, code, my_role: role }) => {
        const grantable = grantableRoles(role)
        return (
          <>
            <PageTitle>{name}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom>
              {name}
            </Typography>
            <Typography sx={{ mb: 1 }}>
              Code {code}. Your role: {ROLE_LABELS[role]}.
            </Typography>
            <Typography sx={{ mb: 3 }}>
              <Link to="/labs/$labId/strains" params={{ labId }}>
                Strains
              </Link>
            </Typography>
            <MemberTable labId={labId} labName={name} grantable={grantable} params={params} onOffsetChange={onOffsetChange} />
            {grantable.length > 0 && <AddMemberForm labId={labId} roles={grantable} />}
          </>
        )
      }}
    </LabGate>
  )
}
