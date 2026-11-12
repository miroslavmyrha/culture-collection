import { LoadError } from '@/components/LoadError'
import { ActionMenu, Box, type ActionItem, Mono, PageTitle, Stack, StatusChip, type Tone, Typography } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { STRAIN_TONES } from '@/lib/tones'
import type { useStrain } from '../api/queries'
import { RESTRICTION_LABELS, STATUS_LABELS, type Strain } from '../schemas'

/** A risk group as a chip: group 1 plain, group 2 to look at, 3 and 4 a warning to everyone. */
const RISK_TONES: Record<number, Tone> = { 1: 'neutral', 2: 'warning', 3: 'danger', 4: 'danger' }

/** What the strain page shows while it has no strain: loading, not found, or the load error, each with its title. */
export function StrainUnavailable({ strain }: { strain: ReturnType<typeof useStrain> }) {
  if (strain.isPending)
    return (
      <>
        <PageTitle>Loading the strain</PageTitle>
        <Typography>Loading the strain…</Typography>
      </>
    )
  // 404 means "not in this lab" as much as "does not exist": the text says both.
  if (isApiError(strain.error, 404))
    return (
      <>
        <PageTitle>Strain not found</PageTitle>
        <Typography component="h1" variant="h4" gutterBottom>
          Strain not found
        </Typography>
        <Typography>The strain does not exist, or it is not in this lab.</Typography>
      </>
    )
  return (
    <>
      <PageTitle>Could not load the strain</PageTitle>
      <LoadError what="the strain" error={strain.error} onRetry={() => void strain.refetch()} />
    </>
  )
}

type HeaderProps = {
  strain: Strain
  /** The strain's actions, for curators and up; none for a deaccessioned strain, which changes no more (#20). */
  actions: ActionItem[] | null
}

/** The header every tab shares: the accession number, the taxon, the actions menu, and the chips. */
export function StrainHeader({ strain: s, actions }: HeaderProps) {
  const number = s.accession_number ?? 'Pending strain'
  const active = s.restriction_history.filter((r) => r.ended_at === null)
  return (
    <Box component="header" sx={{ mb: 2 }}>
      <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography component="h1" variant="h4" sx={{ overflowWrap: 'anywhere' }}>
            <Mono>{number}</Mono>
          </Typography>
          <Typography sx={{ mt: 0.5, overflowWrap: 'anywhere' }}>
            <i>{s.taxon.name}</i> {s.taxon.authority}
          </Typography>
        </Box>
        {actions && <ActionMenu label="Actions" name={`Actions for ${number}`} items={actions} />}
      </Stack>
      <Stack component="ul" aria-label="Biosafety and status" direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap', listStyle: 'none', p: 0, m: 0, mt: 1 }}>
        <li>
          <StatusChip tone={RISK_TONES[s.risk_group] ?? 'neutral'}>Risk group {s.risk_group}</StatusChip>
        </li>
        {active.map((r) => (
          <li key={r.public_id}>
            <StatusChip tone="regulated">{RESTRICTION_LABELS[r.kind]}</StatusChip>
          </li>
        ))}
        <li>
          <StatusChip tone={STRAIN_TONES[s.status] ?? 'neutral'}>{STATUS_LABELS[s.status]}</StatusChip>
        </li>
      </Stack>
    </Box>
  )
}
