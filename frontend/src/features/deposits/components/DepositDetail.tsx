import { type MouseEvent, type ReactNode, useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { Alert, Box, Button, Link, PageTitle, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { countryName } from '@/lib/countries'
import { errorMessage, isApiError } from '@/lib/api'
import { type FocusReturn, rememberFocus, useFocusReturnOnUnmount } from '@/lib/focus'
import { useStartCheck } from '../api/mutations'
import { useDeposit } from '../api/queries'
import {
  ABS_SCOPE_LABELS,
  CONDITION_LABELS,
  DECISION_LABELS,
  type Deposit,
  depositorLabel,
  mtaLabel,
  STATUS_LABELS,
  type Terms,
  USE_LABELS,
} from '../schemas'
import { RejectDialog, ReplaceTermsDialog } from './DepositDialogs'
import { scrollable } from './scroll'

type Props = {
  labId: string
  depositId: string
  canManage: boolean
  /** The acceptance form, given by the page (the strain's facts belong to strains). */
  renderAccept: (deposit: Deposit) => ReactNode
}

type Open = { kind: 'reject' | 'terms'; open: boolean } | null

const day = (iso: string) => new Date(iso).toLocaleDateString('sv')

/**
 * One deposit and its intake, step by step: the receipt, the terms, then the check and the
 * decision. The server's state decides which step is open, so a reload lands on it.
 */
export function DepositDetail({ labId, depositId, canManage, renderAccept }: Props) {
  const deposit = useDeposit(labId, depositId)
  const [open, setOpen] = useState<Open>(null)
  const spot = useRef<FocusReturn | null>(null)
  const show = (kind: NonNullable<Open>['kind']) => (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    setOpen({ kind, open: true })
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }

  if (deposit.isPending)
    return (
      <>
        <PageTitle>Loading the deposit</PageTitle>
        <Typography>Loading the deposit…</Typography>
      </>
    )
  if (isApiError(deposit.error, 404))
    return (
      <>
        <PageTitle>Deposit not found</PageTitle>
        <Typography component="h1" variant="h4" gutterBottom>
          Deposit not found
        </Typography>
        <Typography>The deposit does not exist, or it is not in this lab.</Typography>
      </>
    )
  if (deposit.isError)
    return (
      <>
        <PageTitle>Could not load the deposit</PageTitle>
        <LoadError what="the deposit" error={deposit.error} onRetry={() => void deposit.refetch()} />
      </>
    )
  const d = deposit.data
  const history = d.terms_history.filter((t) => !t.is_active)
  return (
    <>
      <PageTitle>{`Deposit ${d.name_as_received}`}</PageTitle>
      <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
        Deposit {d.name_as_received}
      </Typography>
      <Typography sx={{ mb: 2 }}>Status: {STATUS_LABELS[d.status]}.</Typography>
      <Steps deposit={d} />

      <Section title="Receipt">
        <Facts
          rows={[
            ['Depositor', depositorLabel(d.depositor)],
            ['Received on', d.received_on],
            ['Condition on arrival', CONDITION_LABELS[d.condition]],
            ['Note on the condition', d.condition_note || 'None'],
            ['Passages stated by the depositor', d.depositor_passages === null ? 'Not stated' : String(d.depositor_passages)],
          ]}
        />
      </Section>

      <Section title={`Terms, version ${d.terms.version}`}>
        <TermsFacts terms={d.terms} />
        {canManage && d.status !== 'rejected' && (
          <Box>
            <Button variant="outlined" onClick={show('terms')}>
              Change the terms
            </Button>
          </Box>
        )}
        {history.length > 0 && <TermsHistory rows={history} />}
      </Section>

      <Section title="Check and decision">
        <Decision deposit={d} labId={labId} canManage={canManage} renderAccept={renderAccept} onReject={show('reject')} />
      </Section>

      {/* Mounted until they have faded out, so onExited can place the focus. */}
      {open?.kind === 'reject' && <RejectDialog labId={labId} deposit={d} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'terms' && <ReplaceTermsDialog labId={labId} deposit={d} open={open.open} onClose={close} onExited={exited} />}
    </>
  )
}

/** Where the intake stands, as an ordered list: each step done, open now, or still to come. */
function Steps({ deposit }: { deposit: Deposit }) {
  const decided = deposit.status === 'accepted' || deposit.status === 'rejected'
  const steps: { label: string; state: 'done' | 'now' | 'to come' }[] = [
    { label: `Received on ${deposit.received_on}`, state: 'done' },
    { label: 'Check started', state: deposit.status === 'received' ? 'now' : 'done' },
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

type DecisionProps = { deposit: Deposit; labId: string; canManage: boolean; renderAccept: (deposit: Deposit) => ReactNode; onReject: (event: MouseEvent<HTMLButtonElement>) => void }

function Decision({ deposit, labId, canManage, renderAccept, onReject }: DecisionProps) {
  if (deposit.status === 'accepted' && deposit.strain)
    return (
      <Typography>
        Accepted on {day(deposit.decided_at ?? deposit.created_at)} as strain{' '}
        <Link to="/labs/$labId/strains/$strainId" params={{ labId, strainId: deposit.strain.public_id }}>
          {deposit.strain.accession_number ?? 'pending'}
        </Link>
        . The material as received is its passage 0.
      </Typography>
    )
  if (deposit.status === 'rejected')
    return (
      <Typography sx={{ overflowWrap: 'anywhere' }}>
        Rejected on {day(deposit.decided_at ?? deposit.created_at)}: {deposit.rejection_reason}
      </Typography>
    )
  if (!canManage) return <Typography>{deposit.status === 'received' ? 'The check has not started.' : 'The deposit is being checked.'}</Typography>
  if (deposit.status === 'received') return <StartCheck labId={labId} depositId={deposit.public_id} />
  return (
    <KeepsFocus>
      <Typography>Record what the check found. Accepting creates the strain with its number; rejecting ends the deposit.</Typography>
      {renderAccept(deposit)}
      <Box>
        <Button color="error" variant="outlined" onClick={onReject}>
          Reject the deposit
        </Button>
      </Box>
    </KeepsFocus>
  )
}

/** Its button goes away when the check starts: focus then moves to the section's heading. */
function StartCheck({ labId, depositId }: { labId: string; depositId: string }) {
  const start = useStartCheck(labId, depositId)
  const remember = useFocusReturnOnUnmount()
  const [failure, setFailure] = useState<string>()
  return (
    <Stack spacing={2}>
      <Typography>Start the check when the material is being tested for purity and identity.</Typography>
      <Box>
        <Button
          variant="contained"
          aria-disabled={start.isPending}
          onClick={(event) => {
            if (start.isPending) return
            remember(event.currentTarget)
            setFailure(undefined)
            start.mutate(undefined, {
              onError: (error) =>
                setFailure(isApiError(error, 409) && error.code === 'deposit_state' ? 'The deposit changed meanwhile. Reload the page.' : errorMessage(error)),
            })
          }}
        >
          Start checking
        </Button>
      </Box>
      {failure && <Alert severity="error">{failure}</Alert>}
    </Stack>
  )
}

/**
 * The acceptance form and the reject button go away with the decision: when the focused one
 * is removed, focus moves to the section's heading, never to the body.
 */
function KeepsFocus({ children }: { children: ReactNode }) {
  const remember = useFocusReturnOnUnmount()
  return (
    <Stack spacing={2} onFocus={(event) => remember(event.target)}>
      {children}
    </Stack>
  )
}

function TermsFacts({ terms }: { terms: Terms }) {
  return (
    <>
      <Facts
        rows={[
          ['MTA', terms.mta ? mtaLabel(terms.mta) : 'None'],
          ['ABS scope', ABS_SCOPE_LABELS[terms.abs_scope]],
          ['Country of origin', terms.country_of_origin ? countryName(terms.country_of_origin) : 'Unknown'],
          ['Collection date', terms.collection_date || 'Unknown'],
          ['IRCC', terms.ircc || 'None'],
          ['Permit reference', terms.permit_reference || 'None'],
          ['PIC reference', terms.pic_reference || 'None'],
          ['MAT reference', terms.mat_reference || 'None'],
          ...(terms.reason ? ([['Why this version', terms.reason]] as [string, string][]) : []),
        ]}
      />
      <TableContainer component={Paper} variant="outlined" {...scrollable('Uses')}>
        <Table aria-label="Uses" size="small">
          <TableHead>
            <TableRow>
              <TableCell>Use</TableCell>
              <TableCell>Decision</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {terms.uses.map((u) => (
              <TableRow key={u.use}>
                <TableCell>{USE_LABELS[u.use]}</TableCell>
                <TableCell>{DECISION_LABELS[u.decision]}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </>
  )
}

function TermsHistory({ rows }: { rows: Terms[] }) {
  return (
    <TableContainer component={Paper} variant="outlined" {...scrollable('Earlier terms')}>
      <Table aria-label="Earlier terms" size="small">
        <TableHead>
          <TableRow>
            <TableCell>Version</TableCell>
            <TableCell>From</TableCell>
            <TableCell>MTA</TableCell>
            <TableCell>ABS scope</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((t) => (
            <TableRow key={t.public_id}>
              <TableCell>{t.version}</TableCell>
              <TableCell sx={{ whiteSpace: 'nowrap' }}>{day(t.created_at)}</TableCell>
              <TableCell sx={{ overflowWrap: 'anywhere' }}>{t.mta ? mtaLabel(t.mta) : 'None'}</TableCell>
              <TableCell>{ABS_SCOPE_LABELS[t.abs_scope]}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
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

