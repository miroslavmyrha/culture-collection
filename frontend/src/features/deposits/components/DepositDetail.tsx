import { type MouseEvent, type ReactNode, useRef, useState } from 'react'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Button, PageTitle, Typography } from '@/components/ui'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { useDeposit } from '../api/queries'
import { type Deposit, STATUS_LABELS } from '../schemas'
import { Decision } from './DepositDecision'
import { RejectDialog, ReplaceTermsDialog } from './DepositDialogs'
import { DepositUnavailable, ReceiptFacts, Section, TermsFacts, TermsHistory } from './DepositParts'

type Props = {
  labId: string
  depositId: string
  canManage: boolean
  /** The acceptance form, given by the page (the strain's facts belong to strains). */
  renderAccept: (deposit: Deposit) => ReactNode
}

type Kind = 'reject' | 'terms'
type Open = { kind: Kind; open: boolean } | null

/** The terms can be changed by a manager until the deposit is rejected. */
function ChangeTerms({ show }: { show: (event: MouseEvent<HTMLButtonElement>) => void }) {
  return (
    <Box>
      <Button variant="outlined" onClick={show}>
        Change the terms
      </Button>
    </Box>
  )
}

type HostProps = { open: Open; labId: string; deposit: Deposit; onClose: () => void; onExited: () => void }

/** The dialog the person opened, if any. Mounted until it has faded out, so onExited can place the focus. */
function DepositDialogHost({ open, labId, deposit, onClose, onExited }: HostProps) {
  if (open === null) return null
  const props = { labId, deposit, open: open.open, onClose, onExited }
  return open.kind === 'reject' ? <RejectDialog {...props} /> : <ReplaceTermsDialog {...props} />
}

/**
 * One deposit and its intake, step by step: the receipt, the terms, then the check and the
 * decision. The server's state decides which step is open, so a reload lands on it.
 */
export function DepositDetail({ labId, depositId, canManage, renderAccept }: Props) {
  const deposit = useDeposit(labId, depositId)
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

  if (deposit.data === undefined) return <DepositUnavailable deposit={deposit} />
  const d = deposit.data
  const history = d.terms_history.filter((t) => !t.is_active)
  return (
    <>
      <PageTitle>{`Deposit ${d.name_as_received}`}</PageTitle>
      <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
        Deposit {d.name_as_received}
      </Typography>
      <StaleNotice what="the deposit" query={deposit} />
      <Typography sx={{ mb: 2 }}>Status: {STATUS_LABELS[d.status]}.</Typography>
      <Steps deposit={d} />

      <Section title="Receipt">
        <ReceiptFacts deposit={d} />
      </Section>

      <Section title={`Terms, version ${d.terms.version}`}>
        <TermsFacts terms={d.terms} />
        {canManage && d.status !== 'rejected' && <ChangeTerms show={show('terms')} />}
        {history.length > 0 && <TermsHistory rows={history} />}
      </Section>

      <Section title="Check and decision">
        <Decision deposit={d} labId={labId} canManage={canManage} renderAccept={renderAccept} onReject={show('reject')} />
      </Section>

      <DepositDialogHost open={open} labId={labId} deposit={d} onClose={close} onExited={exited} />
    </>
  )
}

/** Where the intake stands, as an ordered list: each step done, open now, or still to come. */
function Steps({ deposit }: { deposit: Deposit }) {
  const decided = deposit.status === 'accepted' || deposit.status === 'rejected'
  const steps: { label: string; state: 'done' | 'now' | 'to come' }[] = [
    { label: `Received on ${deposit.received_on}`, state: 'done' },
    deposit.status === 'received' ? { label: 'Start the check', state: 'now' } : { label: 'Check started', state: 'done' },
    {
      label: decided ? STATUS_LABELS[deposit.status] : 'Accept or reject',
      state: decided ? 'done' : deposit.status === 'checking' ? 'now' : 'to come',
    },
  ]
  return (
    <Box component="ol" aria-label="Intake steps" sx={{ pl: 3, mb: 3 }}>
      {steps.map((step) => (
        <Typography component="li" key={step.label} aria-current={step.state === 'now' ? 'step' : undefined}>
          {step.label} ({step.state})
        </Typography>
      ))}
    </Box>
  )
}
