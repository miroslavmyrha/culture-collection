import { type MouseEvent, type ReactNode, useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Alert, Box, Button, PageTitle, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { countryName } from '@/lib/countries'
import { type FocusReturn, rememberFocus, useFocusReturnOnUnmount } from '@/lib/focus'
import { useRequest } from '../api/queries'
import {
  BASIS_LABELS,
  canApproveRegulated,
  canPrepare,
  canShip,
  CONFIRM_REFUSALS,
  COOLANT_LABELS,
  type Finding,
  type Line,
  openPreparation,
  PACKING_LABELS,
  type Preparation,
  type Request,
  type Role,
  type Shipment,
  SIGNER_ROLE_LABELS,
  STATUS_LABELS,
  TRANSPORT_CLASS_LABELS,
  USE_LABELS,
} from '../schemas'
import { AcceptanceDialog, ApproveDialog, CancelDialog, ConfirmShipmentDialog, RejectDialog, SECOND_PERSON, ShipDialog, WithdrawShipmentDialog } from './RequestDialogs'
import { scrollable } from './scroll'

type Props = { labId: string; requestId: string; role: Role }
type Kind = 'approve' | 'reject' | 'cancel' | 'acceptance' | 'ship' | 'prepare' | 'confirm' | 'withdraw'
type Open = { kind: Kind; open: boolean; preparation?: Preparation } | null

const day = (iso: string) => new Date(iso).toLocaleDateString('sv')

/**
 * One request: who asks for what and why, each strain with the terms and MTA it was entered
 * under, what the policy finds while it waits, the MTA acceptances, and the decision. After an
 * approval each line lists the vials reserved for it, after the shipment the vials sent, by label
 * only: no place (ADR 0009). A shipped request shows the shipment's facts; its responsible person
 * only to those who may see people. A regulated request leaves in two steps (#89): the shipment
 * prepared by one person waits for a second, who sees it before confirming; a withdrawn
 * preparation stays listed.
 */
export function RequestDetail({ labId, requestId, role }: Props) {
  const request = useRequest(labId, requestId)
  const [open, setOpen] = useState<Open>(null)
  const spot = useRef<FocusReturn | null>(null)
  const show = (kind: Kind) => (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    // The confirmation keeps the preparation it was opened on: a refetch does not swap it.
    setOpen({ kind, open: true, preparation: request.data && openPreparation(request.data) })
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }

  if (request.data === undefined) {
    if (request.isPending)
      return (
        <>
          <PageTitle>Loading the request</PageTitle>
          <Typography>Loading the request…</Typography>
        </>
      )
    if (isApiError(request.error, 404))
      return (
        <>
          <PageTitle>Request not found</PageTitle>
          <Typography component="h1" variant="h4" gutterBottom>
            Request not found
          </Typography>
          <Typography>The request does not exist, or it is not in this lab.</Typography>
        </>
      )
    return (
      <>
        <PageTitle>Could not load the request</PageTitle>
        <LoadError what="the request" error={request.error} onRetry={() => void request.refetch()} />
      </>
    )
  }
  const r = request.data
  const manage = role === 'curator' || role === 'manager'
  const prepared = openPreparation(r)
  const withdrawn = r.preparations.filter((p) => p.withdrawn_at !== null)
  return (
    <>
      <PageTitle>{`Request ${r.number}`}</PageTitle>
      <Typography component="h1" variant="h4" gutterBottom>
        Request {r.number}
      </Typography>
      <StaleNotice what="the request" query={request} />
      <Typography sx={{ mb: 2 }}>Status: {STATUS_LABELS[r.status]}.</Typography>

      <Section title="What is asked">
        <Facts
          rows={[
            ['Requester', `${r.requester.institution}, ${countryName(r.requester.country)}`],
            ['Destination', countryName(r.destination_country)],
            ['Use', USE_LABELS[r.use]],
            ['End use', r.end_use],
            ['Declared containment level', String(r.containment_level)],
            ['Entered by', `${r.submitted_by} on ${day(r.created_at)}`],
          ]}
        />
      </Section>

      <Section title="Strains">
        <Lines lines={r.lines} shipped={r.status === 'shipped'} />
      </Section>

      {r.status === 'submitted' && (
        <Section title="What stands in the way">
          <Findings findings={r.findings} />
        </Section>
      )}

      <Section title="MTA acceptances">
        <Acceptances request={r} />
        {manage && r.status === 'submitted' && (
          <Box>
            <Button variant="outlined" onClick={show('acceptance')}>
              Record an acceptance
            </Button>
          </Box>
        )}
      </Section>

      <Section title="Decision">
        <Decision request={r} role={role} onShow={show} />
      </Section>

      {prepared && (
        <Section title="Prepared shipment">
          <PackageFacts package={prepared} people={[['Prepared by', `${prepared.prepared_by} on ${day(prepared.prepared_at)}`]]} />
        </Section>
      )}

      {r.shipment && (
        <Section title="Shipment">
          <ShipmentFacts shipment={r.shipment} />
        </Section>
      )}

      {withdrawn.length > 0 && (
        <Section title="Withdrawn preparations">
          <Box component="ul" sx={{ pl: 3, my: 0 }}>
            {withdrawn.map((p) => (
              <Typography component="li" key={p.public_id} sx={{ overflowWrap: 'anywhere' }}>
                Prepared by {p.prepared_by} on {day(p.prepared_at)}, withdrawn by {p.withdrawn_by} on {day(p.withdrawn_at ?? p.prepared_at)}
                {reason(p.withdraw_reason)}
              </Typography>
            ))}
          </Box>
        </Section>
      )}

      {/* Mounted until they have faded out, so onExited can place the focus. */}
      {open?.kind === 'approve' && <ApproveDialog labId={labId} request={r} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'reject' && <RejectDialog labId={labId} request={r} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'cancel' && <CancelDialog labId={labId} request={r} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'ship' && <ShipDialog labId={labId} request={r} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'prepare' && <ShipDialog prepare labId={labId} request={r} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'confirm' && open.preparation && (
        <ConfirmShipmentDialog labId={labId} request={r} preparation={open.preparation} open={open.open} onClose={close} onExited={exited}>
          <PackageFacts package={open.preparation} people={[]} />
        </ConfirmShipmentDialog>
      )}
      {open?.kind === 'withdraw' && <WithdrawShipmentDialog labId={labId} request={r} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'acceptance' && <AcceptanceDialog labId={labId} request={r} open={open.open} onClose={close} onExited={exited} />}
    </>
  )
}

function Lines({ lines, shipped }: { lines: Line[]; shipped: boolean }) {
  return (
    <TableContainer component={Paper} variant="outlined" {...scrollable('Strains')}>
      <Table aria-label="Strains" size="small">
        <TableHead>
          <TableRow>
            <TableCell>Strain</TableCell>
            <TableCell>Risk group</TableCell>
            <TableCell>Vials</TableCell>
            <TableCell>Terms and MTA</TableCell>
            <TableCell>{shipped ? 'Shipped vials' : 'Reserved vials'}</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {lines.map((line) => (
            <TableRow key={line.public_id}>
              <TableCell sx={{ overflowWrap: 'anywhere' }}>
                {line.strain.accession_number}, <i>{line.strain.taxon}</i>
              </TableCell>
              <TableCell>{line.strain.risk_group}</TableCell>
              <TableCell>{line.quantity}</TableCell>
              <TableCell sx={{ overflowWrap: 'anywhere' }}>
                Terms version {line.terms_version}, {line.mta ? `MTA ${line.mta.code} version ${line.mta.version}` : 'no MTA'}
              </TableCell>
              <TableCell sx={{ overflowWrap: 'anywhere' }}>{vialLabels(shipped ? line.shipped : line.reserved)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

const vialLabels = (vials: { label: string }[]) => (vials.length ? vials.map((v) => v.label).join('; ') : 'None')

function findingItem(f: Finding) {
  return (
    <Typography component="li" key={`${f.code}-${f.line ?? 'request'}`} data-code={f.code} sx={{ overflowWrap: 'anywhere' }}>
      {f.sentence}
    </Typography>
  )
}

function Findings({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) return <Typography>Nothing stands in the way: a curator may approve it.</Typography>
  const blocks = findings.filter((f) => f.severity === 'block')
  const manager = findings.filter((f) => f.severity === 'manager')
  return (
    <>
      {blocks.length > 0 && (
        <>
          <Typography component="h3" variant="subtitle1" sx={{ fontWeight: 'bold' }}>
            Blocks the approval
          </Typography>
          <Box component="ul" aria-label="Blocks the approval" sx={{ pl: 3, my: 0 }}>
            {blocks.map(findingItem)}
          </Box>
        </>
      )}
      {manager.length > 0 && (
        <>
          <Typography component="h3" variant="subtitle1" sx={{ fontWeight: 'bold' }}>
            Needs a manager’s approval
          </Typography>
          <Box component="ul" aria-label="Needs a manager’s approval" sx={{ pl: 3, my: 0 }}>
            {manager.map(findingItem)}
          </Box>
        </>
      )}
    </>
  )
}

function Acceptances({ request }: { request: Request }) {
  if (request.acceptances.length === 0) return <Typography>No acceptance is recorded yet.</Typography>
  return (
    <Box component="ul" sx={{ pl: 3, my: 0 }}>
      {request.acceptances.map((a) => (
        <Typography component="li" key={a.public_id} sx={{ overflowWrap: 'anywhere' }}>
          MTA {a.mta.code} version {a.mta.version}, accepted on {a.accepted_on} by {a.signer_name ?? 'the requester'} ({SIGNER_ROLE_LABELS[a.signer_role]}
          {a.authorised_signatory ? ', may bind the institution' : ', may not bind the institution'})
        </Typography>
      ))}
    </Box>
  )
}

const reason = (text: string) => (text ? `: ${text}` : '.')

type DecisionProps = { request: Request; role: Role; onShow: (kind: Kind) => (event: MouseEvent<HTMLButtonElement>) => void }

function Decision({ request, role, onShow }: DecisionProps) {
  const manage = role === 'curator' || role === 'manager'
  if (request.status === 'rejected')
    return <Typography sx={{ overflowWrap: 'anywhere' }}>Rejected by {request.decided_by} on {day(request.decided_at ?? request.created_at)}{reason(request.decision_reason)}</Typography>
  if (request.status === 'cancelled')
    return <Typography sx={{ overflowWrap: 'anywhere' }}>Cancelled by {request.cancelled_by} on {day(request.cancelled_at ?? request.created_at)}{reason(request.cancel_reason)}</Typography>
  const approval = `Approved by ${request.decided_by ?? ''} on ${day(request.decided_at ?? request.created_at)}${reason(request.decision_reason)}`
  const s = request.shipment
  if (request.status === 'shipped')
    return (
      <Typography sx={{ overflowWrap: 'anywhere' }}>
        {approval}{' '}
        {s?.preparation
          ? `Prepared by ${s.classified_by} on ${day(s.classified_at)}, confirmed and shipped by ${s.shipped_by} on ${day(s.shipped_at)}.`
          : `Shipped by ${s?.shipped_by ?? ''} on ${day(s?.shipped_at ?? request.created_at)}.`}
      </Typography>
    )
  const prepared = openPreparation(request)
  if (prepared)
    return (
      <KeepsFocus>
        <Typography sx={{ overflowWrap: 'anywhere' }}>
          {approval} The shipment was prepared by {prepared.prepared_by} on {day(prepared.prepared_at)} and waits for a second person to confirm it. The vials stay reserved until then.
        </Typography>
        {manage && prepared.confirm_refusal && <Alert severity="info">{CONFIRM_REFUSALS[prepared.confirm_refusal]}</Alert>}
        {manage && (
          <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap' }}>
            {!prepared.confirm_refusal && (
              <Button variant="contained" onClick={onShow('confirm')}>
                Confirm the shipment
              </Button>
            )}
            <Button color="error" variant="outlined" onClick={onShow('withdraw')}>
              Withdraw the prepared shipment
            </Button>
          </Stack>
        )}
      </KeepsFocus>
    )
  if (request.status === 'approved')
    return (
      <KeepsFocus>
        <Typography sx={{ overflowWrap: 'anywhere' }}>{approval} The vials stay reserved until the shipment or a cancellation.</Typography>
        {manage && request.regulated && <Alert severity="info">{SECOND_PERSON}</Alert>}
        {manage && (
          <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap' }}>
            {canShip(request, role) && (
              <Button variant="contained" onClick={onShow('ship')}>
                Ship the vials
              </Button>
            )}
            {canPrepare(request, role) && (
              <Button variant="contained" onClick={onShow('prepare')}>
                Prepare the shipment
              </Button>
            )}
            <Button color="error" variant="outlined" onClick={onShow('cancel')}>
              Cancel the request
            </Button>
          </Stack>
        )}
      </KeepsFocus>
    )
  if (!manage) return <Typography>The request waits for a curator’s decision.</Typography>
  const blocked = request.findings.some((f) => f.severity === 'block')
  const needsManager = request.findings.some((f) => f.severity === 'manager')
  return (
    <KeepsFocus>
      {blocked && <Alert severity="info">It cannot be approved while something blocks it. Reject it, or wait for what is missing.</Alert>}
      {!blocked && needsManager && !canApproveRegulated(role) && <Alert severity="info">A manager approves this request.</Alert>}
      <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap' }}>
        {!blocked && (!needsManager || canApproveRegulated(role)) && (
          <Button variant="contained" onClick={onShow('approve')}>
            Approve and reserve the vials
          </Button>
        )}
        <Button color="error" variant="outlined" onClick={onShow('reject')}>
          Reject the request
        </Button>
        <Button variant="outlined" onClick={onShow('cancel')}>
          Cancel the request
        </Button>
      </Stack>
    </KeepsFocus>
  )
}

function ShipmentFacts({ shipment: s }: { shipment: Shipment }) {
  const people: [string, string][] = s.preparation
    ? [
        ['Prepared and classified by', `${s.classified_by} on ${day(s.classified_at)}`],
        ['Confirmed by', `${s.shipped_by} on ${day(s.shipped_at)}`],
      ]
    : [['Classified by', `${s.classified_by} on ${day(s.classified_at)}`]]
  return <PackageFacts package={s} people={people} />
}

/** What the shipper decided about a package, shipped or prepared, and who answers for it. */
function PackageFacts({ package: s, people }: { package: Shipment | Preparation; people: [string, string][] }) {
  const rows: [string, string][] = [
    ['Transport class', TRANSPORT_CLASS_LABELS[s.transport_class]],
    ['Basis', s.basis_note ? `${BASIS_LABELS[s.classification_basis]}: ${s.basis_note}` : BASIS_LABELS[s.classification_basis]],
    ...people,
    ['Packing', PACKING_LABELS[s.packing_instruction]],
    ['Coolant', s.coolant ? `${COOLANT_LABELS[s.coolant]}${s.coolant_kg ? `, ${s.coolant_kg} kg` : ''}` : 'None'],
  ]
  // Null for a role that may not see people; empty once the person was erased.
  if (s.responsible_name !== null) rows.push(['Responsible person', s.responsible_name ? `${s.responsible_name}, ${s.responsible_phone ?? ''}` : 'Erased contact'])
  rows.push(['Carrier', s.carrier], ['Tracking number', s.tracking_number || 'None'])
  return <Facts rows={rows} />
}

/** The decision buttons go away with the decision: focus then moves to the section's heading. */
function KeepsFocus({ children }: { children: ReactNode }) {
  const remember = useFocusReturnOnUnmount()
  return (
    <Stack spacing={2} onFocus={(event) => remember(event.target)}>
      {children}
    </Stack>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Box component="section" aria-label={title} sx={{ mt: 4 }}>
      {/* tabIndex -1: where focus goes when the control that had it is gone. */}
      <Typography component="h2" variant="h6" tabIndex={-1} gutterBottom>
        {title}
      </Typography>
      <Stack spacing={2}>{children}</Stack>
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
