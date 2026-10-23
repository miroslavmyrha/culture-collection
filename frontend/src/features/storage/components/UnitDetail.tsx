import { type MouseEvent, type ReactNode, useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Button, Link, PageTitle, Stack, StatusChip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { UNIT_TONES } from '@/lib/tones'
import { isApiError } from '@/lib/api'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { useUnit } from '../api/queries'
import { degrees, HOLDS, isRoot, KIND_LABELS, KIND_WORDS, sizeLabel, STATUS_LABELS, type Unit } from '../schemas'
import { CreateUnitDialog, EditUnitDialog, MoveUnitDialog, UnitStatusDialog } from './UnitDialogs'

type Props = {
  labId: string
  labName: string
  unitId: string
  canManage: boolean
  /** After a unit is added inside this one: show it. */
  onCreated: (unit: Unit) => void
  /** What the unit holds besides units (a box's positions), from the page: features do not import each other. */
  renderContents?: (unit: Unit) => ReactNode
}

type Kind = 'add' | 'edit' | 'move' | 'out_of_service' | 'active' | 'retired'
type Open = { kind: Kind; open: boolean } | null

/** One storage unit: where it is (breadcrumbs), what it is, what it holds, and for curators the actions. */
export function UnitDetail({ labId, labName, unitId, canManage, onCreated, renderContents }: Props) {
  const unit = useUnit(labId, unitId)
  const [open, setOpen] = useState<Open>(null)
  const spot = useRef<FocusReturn | null>(null)
  const show = (kind: Kind) => (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    setOpen({ kind, open: true })
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }

  if (unit.data === undefined) {
    if (unit.isPending)
      return (
        <>
          <PageTitle>Loading the unit</PageTitle>
          <Typography>Loading the unit…</Typography>
        </>
      )
    // 404 means "not in this lab" as much as "does not exist": the text says both.
    if (isApiError(unit.error, 404))
      return (
        <>
          <PageTitle>Unit not found</PageTitle>
          <Typography component="h1" variant="h4" gutterBottom>
            Unit not found
          </Typography>
          <Typography>The storage unit does not exist, or it is not in this lab.</Typography>
        </>
      )
    return (
      <>
        <PageTitle>Could not load the unit</PageTitle>
        <LoadError what="the unit" error={unit.error} onRetry={() => void unit.refetch()} />
      </>
    )
  }
  const u = unit.data
  const above = u.ancestors.at(-1)
  const holds = HOLDS[u.kind]
  const retired = u.status === 'retired'
  return (
    <>
      <PageTitle>{above ? `${u.name} in ${above.name}` : u.name}</PageTitle>
      <Box component="nav" aria-label="Breadcrumb" sx={{ mb: 2 }}>
        <Box component="ol" sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, listStyle: 'none', m: 0, p: 0 }}>
          <Crumb>
            <Link to="/labs/$labId/storage" params={{ labId }}>
              Storage of {labName}
            </Link>
          </Crumb>
          {u.ancestors.map((a) => (
            <Crumb key={a.public_id}>
              <Link to="/labs/$labId/storage/$unitId" params={{ labId, unitId: a.public_id }}>
                {a.name}
              </Link>
            </Crumb>
          ))}
          <Crumb current>{u.name}</Crumb>
        </Box>
      </Box>
      <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
        {u.name}
      </Typography>
      <StaleNotice what="the unit" query={unit} />

      <Facts
        rows={[
          ['Kind', KIND_LABELS[u.kind]],
          ['Status', STATUS_LABELS[u.status] + (u.status === 'active' && !u.path_active ? ', but a unit holding it is not' : '')],
          ...(u.slot === null ? [] : [['Slot', String(u.slot)] as [string, string]]),
          ...(u.rows === null || u.cols === null ? [] : [['Size', sizeLabel(u.rows, u.cols)] as [string, string]]),
          ...(u.box_type ? [['Box type', u.box_type.name] as [string, string]] : []),
          ...(u.temperature_c === null ? [] : [['Temperature', degrees(u.temperature_c)] as [string, string]]),
          ['Highest risk group', riskCap(u)],
          ['Barcode', u.barcode ?? 'None'],
        ]}
      />

      {canManage && !retired && (
        <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap', my: 3 }}>
          {holds.length > 0 && u.status === 'active' && (
            <Button variant="contained" onClick={show('add')}>
              Add a {holds.map((k) => KIND_WORDS[k]).join(' or ')}
            </Button>
          )}
          <Button variant="outlined" onClick={show('edit')}>
            Change
          </Button>
          {!isRoot(u.kind) && (
            <Button variant="outlined" onClick={show('move')}>
              Move
            </Button>
          )}
          {u.status === 'active' ? (
            <Button variant="outlined" onClick={show('out_of_service')}>
              Put out of service
            </Button>
          ) : (
            <Button variant="outlined" onClick={show('active')}>
              Put back in service
            </Button>
          )}
          <Button variant="outlined" color="error" onClick={show('retired')}>
            Retire
          </Button>
        </Stack>
      )}

      {holds.length > 0 && (
        <Box component="section" aria-label="Holds" sx={{ mt: 4 }}>
          {/* tabIndex -1: where focus goes when the control that had it is gone. */}
          <Typography component="h2" variant="h6" tabIndex={-1} gutterBottom>
            Holds
          </Typography>
          {u.children.length === 0 ? (
            <Typography>Nothing yet.</Typography>
          ) : (
            // A table that may scroll sideways and holds links only: a named, focusable region, so
            // the arrow keys can scroll it (WCAG 2.1.1).
            <TableContainer
              component="section"
              tabIndex={0}
              aria-label="Holds table"
              sx={{ border: 1, borderColor: 'divider', borderRadius: 1, '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 2 } }}
            >
              <Table aria-label={`What ${u.name} holds`}>
                <TableHead>
                  <TableRow>
                    <TableCell>Slot</TableCell>
                    <TableCell>Name</TableCell>
                    <TableCell>Kind</TableCell>
                    <TableCell>Size</TableCell>
                    <TableCell>Status</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {u.children.map((c) => (
                    <TableRow key={c.public_id}>
                      <TableCell>{c.slot ?? ''}</TableCell>
                      <TableCell sx={{ overflowWrap: 'anywhere' }}>
                        <Link to="/labs/$labId/storage/$unitId" params={{ labId, unitId: c.public_id }}>
                          {c.name}
                        </Link>
                      </TableCell>
                      <TableCell>{KIND_LABELS[c.kind]}</TableCell>
                      <TableCell sx={{ whiteSpace: 'nowrap' }}>{c.rows !== null && c.cols !== null ? `${c.rows} x ${c.cols}` : ''}</TableCell>
                      <TableCell>
                        <StatusChip tone={UNIT_TONES[c.status]}>{STATUS_LABELS[c.status]}</StatusChip>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Box>
      )}

      {renderContents?.(u)}

      {/* Mounted until they have faded out, so onExited can place the focus. */}
      {open?.kind === 'add' && <CreateUnitDialog labId={labId} parent={u} open={open.open} onClose={close} onExited={exited} onCreated={onCreated} />}
      {open?.kind === 'edit' && <EditUnitDialog labId={labId} unit={u} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'move' && <MoveUnitDialog labId={labId} unit={u} open={open.open} onClose={close} onExited={exited} />}
      {(open?.kind === 'out_of_service' || open?.kind === 'active' || open?.kind === 'retired') && (
        <UnitStatusDialog labId={labId} unit={u} to={open.kind} open={open.open} onClose={close} onExited={exited} />
      )}
    </>
  )
}

/** "2, its own" or "1, set by Freezer A": the cap that holds and where it comes from. */
function riskCap(u: Unit): string {
  if (u.max_risk_group !== null && u.max_risk_group === u.effective_max_risk_group) return `${u.max_risk_group}`
  if (u.max_risk_group !== null) return `${u.effective_max_risk_group}, lower above it than its own ${u.max_risk_group}`
  return `${u.effective_max_risk_group}, set above it`
}

function Crumb({ children, current = false }: { children: ReactNode; current?: boolean }) {
  return (
    <Box component="li" aria-current={current ? 'page' : undefined} sx={{ display: 'flex', gap: 1, overflowWrap: 'anywhere' }}>
      {children}
      {!current && (
        <Box component="span" aria-hidden sx={{ color: 'text.secondary' }}>
          /
        </Box>
      )}
    </Box>
  )
}

function Facts({ rows }: { rows: [string, string][] }) {
  return (
    <Box component="dl" sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'max-content 1fr' }, columnGap: 3, rowGap: 1, m: 0 }}>
      {rows.map(([label, value]) => (
        <Box key={label} sx={{ display: 'contents' }}>
          <Typography component="dt" sx={{ fontWeight: 'bold' }}>
            {label}
          </Typography>
          <Typography component="dd" sx={{ m: 0, overflowWrap: 'anywhere' }}>
            {value}
          </Typography>
        </Box>
      ))}
    </Box>
  )
}
