import { Link, PageTitle, Stack, Typography } from '@/components/ui'
import { canSeeDeposits, grantableRoles, type PageParams, ROLE_LABELS } from '../schemas'
import { AddMemberForm } from './AddMemberForm'
import { LabGate } from './LabGate'
import { MemberTable } from './MemberTable'

type Props = { labId: string; params: PageParams; onOffsetChange: (offset: number) => void }

/** One lab: its name, my role, its strains and storage, its members, and for managers the controls to manage them. */
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
            <Stack direction="row" spacing={2} useFlexGap component="nav" aria-label="Lab sections" sx={{ flexWrap: 'wrap', mb: 3 }}>
              <Link to="/labs/$labId/strains" params={{ labId }}>
                Strains
              </Link>
              <Link to="/labs/$labId/storage" params={{ labId }}>
                Storage
              </Link>
              <Link to="/labs/$labId/requests" params={{ labId }}>
                Requests
              </Link>
              {canSeeDeposits(role) && (
                <>
                  <Link to="/labs/$labId/deposits" params={{ labId }}>
                    Deposits
                  </Link>
                  <Link to="/labs/$labId/depositors" params={{ labId }}>
                    Depositors
                  </Link>
                  <Link to="/labs/$labId/mta-templates" params={{ labId }}>
                    MTA templates
                  </Link>
                </>
              )}
            </Stack>
            <MemberTable labId={labId} labName={name} grantable={grantable} params={params} onOffsetChange={onOffsetChange} />
            {grantable.length > 0 && <AddMemberForm labId={labId} roles={grantable} />}
          </>
        )
      }}
    </LabGate>
  )
}
