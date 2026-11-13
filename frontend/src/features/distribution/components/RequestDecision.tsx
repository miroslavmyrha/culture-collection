import { type MouseEvent } from 'react'
import { Alert, Button, Typography } from '@/components/ui'
import { SECOND_PERSON } from '../requestErrors'
import { canApproveRegulated, canPrepare, canShip, CONFIRM_REFUSALS, openPreparation, type Preparation, type Request, type Role } from '../schemas'
import { ButtonRow, canManage, day, KeepsFocus, reason } from './requestParts'

export type Kind = 'approve' | 'reject' | 'cancel' | 'acceptance' | 'ship' | 'prepare' | 'confirm' | 'withdraw' | 'yes' | 'no'
export type OnShow = (kind: Kind) => (event: MouseEvent<HTMLButtonElement>) => void

type Props = { request: Request; role: Role; onShow: OnShow }

const approvalText = (request: Request) => `Approved by ${request.decided_by ?? ''} on ${day(request.decided_at ?? request.created_at)}${reason(request.decision_reason)}`

/**
 * What the approval of a submitted request waits for. A finding that blocks stops it for everyone,
 * one that needs a manager stops a curator, and the page says which of the two it is.
 */
export function approvalGate(request: Request, role: Role) {
  const blocked = request.findings.some((f) => f.severity === 'block')
  const needsManager = request.findings.some((f) => f.severity === 'manager')
  return { blocked, managerOnly: !blocked && needsManager && !canApproveRegulated(role), canApprove: !blocked && (!needsManager || canApproveRegulated(role)) }
}

/**
 * The decision on a request, by where it stands. A request that waits for a second person is
 * told by its open preparation, not by its status: without one it falls to the submitted case.
 */
export function Decision({ request, role, onShow }: Props) {
  if (request.status === 'rejected') return <Rejected request={request} />
  if (request.status === 'cancelled') return <Cancelled request={request} />
  if (request.status === 'shipped') return <Shipped request={request} />
  const prepared = openPreparation(request)
  if (prepared) return <Prepared request={request} prepared={prepared} manage={canManage(role)} onShow={onShow} />
  if (request.status === 'approved') return <Approved request={request} role={role} onShow={onShow} />
  return <Submitted request={request} role={role} onShow={onShow} />
}

function Rejected({ request }: { request: Request }) {
  return <Typography sx={{ overflowWrap: 'anywhere' }}>Rejected by {request.decided_by} on {day(request.decided_at ?? request.created_at)}{reason(request.decision_reason)}</Typography>
}

function Cancelled({ request }: { request: Request }) {
  return <Typography sx={{ overflowWrap: 'anywhere' }}>Cancelled by {request.cancelled_by} on {day(request.cancelled_at ?? request.created_at)}{reason(request.cancel_reason)}</Typography>
}

function shipText(request: Request) {
  const s = request.shipment
  if (s?.preparation) return `Prepared by ${s.classified_by} on ${day(s.classified_at)}, confirmed and shipped by ${s.shipped_by} on ${day(s.shipped_at)}.`
  return `Shipped by ${s?.shipped_by ?? ''} on ${day(s?.shipped_at ?? request.created_at)}.`
}

function Shipped({ request }: { request: Request }) {
  return (
    <Typography sx={{ overflowWrap: 'anywhere' }}>
      {approvalText(request)} {shipText(request)}
    </Typography>
  )
}

function Prepared({ request, prepared, manage, onShow }: { request: Request; prepared: Preparation; manage: boolean; onShow: OnShow }) {
  return (
    <KeepsFocus>
      <Typography sx={{ overflowWrap: 'anywhere' }}>
        {approvalText(request)} The shipment was prepared by {prepared.prepared_by} on {day(prepared.prepared_at)} and waits for a second person to confirm it. The vials stay reserved until then.
      </Typography>
      {manage && prepared.confirm_refusal && <Alert severity="info">{CONFIRM_REFUSALS[prepared.confirm_refusal]}</Alert>}
      {manage && (
        <ButtonRow>
          {!prepared.confirm_refusal && (
            <Button variant="contained" onClick={onShow('confirm')}>
              Confirm the shipment
            </Button>
          )}
          <Button color="error" variant="outlined" onClick={onShow('withdraw')}>
            Withdraw the prepared shipment
          </Button>
        </ButtonRow>
      )}
    </KeepsFocus>
  )
}

function Approved({ request, role, onShow }: Props) {
  const manage = canManage(role)
  return (
    <KeepsFocus>
      <Typography sx={{ overflowWrap: 'anywhere' }}>{approvalText(request)} The vials stay reserved until the shipment or a cancellation.</Typography>
      {manage && request.regulated && <Alert severity="info">{SECOND_PERSON}</Alert>}
      {manage && (
        <ButtonRow>
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
        </ButtonRow>
      )}
    </KeepsFocus>
  )
}

function Submitted({ request, role, onShow }: Props) {
  if (!canManage(role)) return <Typography>The request waits for a curator’s decision.</Typography>
  const gate = approvalGate(request, role)
  return (
    <KeepsFocus>
      {gate.blocked && <Alert severity="info">It cannot be approved while something blocks it. Reject it, or wait for what is missing.</Alert>}
      {gate.managerOnly && <Alert severity="info">A manager approves this request.</Alert>}
      <ButtonRow>
        {gate.canApprove && (
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
      </ButtonRow>
    </KeepsFocus>
  )
}
