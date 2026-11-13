import { type ComponentType, type MouseEvent, type ReactNode, useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { PageTitle, Typography, Mono } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { useRequest } from '../api/queries'
import { awaitingAnswer, type Line, openPreparation, type Preparation, type Request, type Role, STATUS_LABELS } from '../schemas'
import { AcceptanceDialog, ApproveDialog, CancelDialog, type Common, ConfirmShipmentDialog, DepositorAnswerDialog, RejectDialog, ShipDialog, WithdrawShipmentDialog } from './RequestDialogs'
import { type Kind } from './RequestDecision'
import { AcceptancesSection, AnswersSection, AskedSection, DecisionSection, FindingsSection, PreparedSection, ShipmentSections, StrainsSection, VialsSection, WithdrawnSection } from './RequestSections'
import { PackageFacts } from './requestParts'

type Props = {
  labId: string
  requestId: string
  role: Role
  /** Where the reserved vials lie (#143): the page composes the vials feature here. */
  renderVials?: (request: Request) => ReactNode
}
type Open = { kind: Kind; open: boolean; preparation?: Preparation; lines?: Line[] } | null

/**
 * One request: who asks for what and why, each strain with the terms and MTA it was entered
 * under, what the policy finds while it waits, the MTA acceptances, and the decision. After an
 * approval each line lists the vials reserved for it, after the shipment the vials sent, by label.
 * While vials are reserved, "Vials to pull" (renderVials) lists them with their places, in the
 * order of one walk through the storage, masked for a regulated strain (#143, ADR 0009). A shipped request shows the shipment's facts; its responsible person
 * only to those who may see people. A regulated request leaves in two steps (#89): the shipment
 * prepared by one person waits for a second, who sees it before confirming; a withdrawn
 * preparation stays listed. A shipped request lists the documents written with it (#90).
 */
export function RequestDetail({ labId, requestId, role, renderVials }: Props) {
  const request = useRequest(labId, requestId)
  const [open, setOpen] = useState<Open>(null)
  const spot = useRef<FocusReturn | null>(null)
  const show = (kind: Kind) => (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    // The confirmation keeps the preparation it was opened on: a refetch does not swap it.
    // The answer keeps the strains it was opened on: a refetch does not change the choice.
    setOpen({ kind, open: true, preparation: request.data && openPreparation(request.data), lines: request.data && awaitingAnswer(request.data) })
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }

  const r = request.data
  if (r === undefined) return <RequestMissing query={request} />
  return (
    <>
      <PageTitle>{`Request ${r.number}`}</PageTitle>
      <Typography component="h1" variant="h4" gutterBottom>
        Request <Mono>{r.number}</Mono>
      </Typography>
      <StaleNotice what="the request" query={request} />
      <Typography sx={{ mb: 2 }}>Status: {STATUS_LABELS[r.status]}.</Typography>

      <AskedSection request={r} />
      <StrainsSection request={r} />
      <VialsSection request={r} renderVials={renderVials} />
      <FindingsSection request={r} />
      <AnswersSection labId={labId} request={r} role={role} onShow={show} />
      <AcceptancesSection request={r} role={role} onShow={show} />
      <DecisionSection request={r} role={role} onShow={show} />
      <PreparedSection request={r} />
      <ShipmentSections labId={labId} request={r} role={role} />
      <WithdrawnSection request={r} />

      {/* Mounted until they have faded out, so onExited can place the focus. */}
      <OpenDialog labId={labId} request={r} open={open} onClose={close} onExited={exited} />
    </>
  )
}

/** What the page says while there is no request to show: loading, not found, or the load failed. */
function RequestMissing({ query }: { query: ReturnType<typeof useRequest> }) {
  if (query.isPending)
    return (
      <>
        <PageTitle>Loading the request</PageTitle>
        <Typography>Loading the request…</Typography>
      </>
    )
  if (isApiError(query.error, 404))
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
      <LoadError what="the request" error={query.error} onRetry={() => void query.refetch()} />
    </>
  )
}

const PrepareDialog = (props: Common) => <ShipDialog prepare {...props} />

/** The dialogs that need nothing from the page beyond the request. */
const DIALOGS: Record<Exclude<Kind, 'confirm' | 'yes' | 'no'>, ComponentType<Common>> = {
  approve: ApproveDialog,
  reject: RejectDialog,
  cancel: CancelDialog,
  ship: ShipDialog,
  prepare: PrepareDialog,
  withdraw: WithdrawShipmentDialog,
  acceptance: AcceptanceDialog,
}

function OpenDialog({ labId, request, open, onClose, onExited }: Omit<Common, 'open'> & { open: Open }) {
  if (!open) return null
  const common = { labId, request, open: open.open, onClose, onExited }
  if (open.kind === 'yes' || open.kind === 'no') return <DepositorAnswerDialog {...common} lines={open.lines ?? []} agreed={open.kind === 'yes'} />
  if (open.kind === 'confirm')
    return (
      open.preparation && (
        <ConfirmShipmentDialog {...common} preparation={open.preparation}>
          <PackageFacts package={open.preparation} people={[]} />
        </ConfirmShipmentDialog>
      )
    )
  const Dialog = DIALOGS[open.kind]
  return <Dialog {...common} />
}
