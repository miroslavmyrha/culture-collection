import { type ReactNode, useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { ActionMenu, Box, Mono, PageTitle, Stack, StatusChip, type Tone, Typography } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { STRAIN_TONES } from '@/lib/tones'
import { useStrain } from '../api/queries'
import { RESTRICTION_LABELS, STATUS_LABELS, type Strain } from '../schemas'
import { AddRestrictionDialog, ReclassifyDialog, RiskGroupDialog } from './StrainDialogs'

type Props = {
  labId: string
  strainId: string
  canManage: boolean
  /** The tabs and the open tab, rendered once the strain is there. */
  children: (strain: Strain) => ReactNode
}

type Open = { kind: 'reclassify' | 'risk' | 'add'; open: boolean } | null

/** A risk group as a chip: group 1 plain, group 2 to look at, 3 and 4 a warning to everyone. */
const RISK_TONES: Record<number, Tone> = { 1: 'neutral', 2: 'warning', 3: 'danger', 4: 'danger' }

/**
 * A strain's page around its tabs (#19): the strain's loading, not found and error states, each
 * with its title, and once it is there the header every tab shares: the accession number, the
 * taxon, the risk group, the active restrictions and the status as chips, and the strain's
 * actions in one menu for curators and up. The tab renders the page title.
 */
export function StrainShell({ labId, strainId, canManage, children }: Props) {
  const strain = useStrain(labId, strainId)
  const [open, setOpen] = useState<Open>(null)
  const spot = useRef<FocusReturn | null>(null)
  const show = (kind: NonNullable<Open>['kind']) => (button: HTMLButtonElement) => {
    spot.current = rememberFocus(button)
    setOpen({ kind, open: true })
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }

  if (strain.data === undefined) {
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
  const s = strain.data
  const number = s.accession_number ?? 'Pending strain'
  const active = s.restriction_history.filter((r) => r.ended_at === null)
  return (
    <>
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
          {canManage && (
            <ActionMenu
              label="Actions"
              name={`Actions for ${number}`}
              items={[
                { label: 'Reclassify', onSelect: show('reclassify') },
                { label: 'Change risk group', onSelect: show('risk') },
                { label: 'Add a restriction', onSelect: show('add') },
              ]}
            />
          )}
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
      <StaleNotice what="the strain" query={strain} />
      {children(s)}

      {/* Mounted until they have faded out, so onExited can place the focus. */}
      {open?.kind === 'reclassify' && <ReclassifyDialog labId={labId} strain={s} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'risk' && <RiskGroupDialog labId={labId} strain={s} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'add' && <AddRestrictionDialog labId={labId} strain={s} open={open.open} onClose={close} onExited={exited} />}
    </>
  )
}
