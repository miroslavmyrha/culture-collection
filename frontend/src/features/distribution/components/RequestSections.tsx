import { type ReactNode } from 'react'
import { Box, Button, Mono, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { countryName } from '@/lib/countries'
import { safeHref } from '@/lib/safe'
import { awaitingAnswer, fileHref, type Finding, type Line, openPreparation, type Request, type Role, SIGNER_ROLE_LABELS, USE_LABELS } from '../schemas'
import { ShipmentDocuments } from './ShipmentDocuments'
import { Decision, type OnShow } from './RequestDecision'
import { ButtonRow, canManage, day, Facts, KeepsFocus, PackageFacts, reason, Section, ShipmentFacts } from './requestParts'
import { scrollable } from './scroll'

/** The sections of the request page, each one a part a person reads on its own. */

export function AskedSection({ request: r }: { request: Request }) {
  return (
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
  )
}

export function StrainsSection({ request: r }: { request: Request }) {
  return (
    <Section title="Strains">
      <Lines lines={r.lines} shipped={r.status === 'shipped'} />
    </Section>
  )
}

const VIALS_STATUSES: readonly Request['status'][] = ['approved', 'awaiting_confirmation']

export function VialsSection({ request: r, renderVials }: { request: Request; renderVials?: (request: Request) => ReactNode }) {
  if (!renderVials || !VIALS_STATUSES.includes(r.status)) return null
  return <Section title="Vials to pull">{renderVials(r)}</Section>
}

export function FindingsSection({ request: r }: { request: Request }) {
  if (r.status !== 'submitted') return null
  return (
    <Section title="What stands in the way">
      <Findings findings={r.findings} />
    </Section>
  )
}

export function AnswersSection({ labId, request: r, role, onShow }: { labId: string; request: Request; role: Role; onShow: OnShow }) {
  if (!r.lines.some((l) => l.on_request)) return null
  return (
    <Section title="Depositor’s answers">
      <Answers labId={labId} request={r} role={role} />
      {canManage(role) && awaitingAnswer(r).length > 0 && (
        <KeepsFocus>
          <ButtonRow>
            <Button variant="outlined" onClick={onShow('yes')}>
              Record the depositor’s yes
            </Button>
            <Button color="error" variant="outlined" onClick={onShow('no')}>
              Record the depositor’s no
            </Button>
          </ButtonRow>
        </KeepsFocus>
      )}
    </Section>
  )
}

export function AcceptancesSection({ request: r, role, onShow }: { request: Request; role: Role; onShow: OnShow }) {
  return (
    <Section title="MTA acceptances">
      <Acceptances request={r} />
      {canManage(role) && r.status === 'submitted' && (
        <Box>
          <Button variant="outlined" onClick={onShow('acceptance')}>
            Record an acceptance
          </Button>
        </Box>
      )}
    </Section>
  )
}

export function DecisionSection({ request, role, onShow }: { request: Request; role: Role; onShow: OnShow }) {
  return (
    <Section title="Decision">
      <Decision request={request} role={role} onShow={onShow} />
    </Section>
  )
}

export function PreparedSection({ request }: { request: Request }) {
  const prepared = openPreparation(request)
  if (!prepared) return null
  return (
    <Section title="Prepared shipment">
      <PackageFacts package={prepared} people={[['Prepared by', `${prepared.prepared_by} on ${day(prepared.prepared_at)}`]]} />
    </Section>
  )
}

export function ShipmentSections({ labId, request: r, role }: { labId: string; request: Request; role: Role }) {
  if (!r.shipment) return null
  return (
    <>
      <Section title="Shipment">
        <ShipmentFacts shipment={r.shipment} />
      </Section>
      <Section title="Documents">
        <ShipmentDocuments labId={labId} documents={r.shipment.documents} role={role} />
      </Section>
    </>
  )
}

export function WithdrawnSection({ request }: { request: Request }) {
  const withdrawn = request.preparations.filter((p) => p.withdrawn_at !== null)
  if (withdrawn.length === 0) return null
  return (
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
  )
}

const vialLabels = (vials: { label: string }[]) => (vials.length ? vials.map((v) => v.label).join('; ') : 'None')

const mtaText = (line: Line) => (line.mta ? `MTA ${line.mta.code} version ${line.mta.version}` : 'no MTA')

function LineRow({ line, shipped }: { line: Line; shipped: boolean }) {
  return (
    <TableRow>
      <TableCell sx={{ overflowWrap: 'anywhere' }}>
        <Mono>{line.strain.accession_number}</Mono>, <i>{line.strain.taxon}</i>
      </TableCell>
      <TableCell>{line.strain.risk_group}</TableCell>
      <TableCell>{line.quantity}</TableCell>
      <TableCell sx={{ overflowWrap: 'anywhere' }}>
        Terms version {line.terms_version}, {mtaText(line)}
      </TableCell>
      <TableCell sx={{ overflowWrap: 'anywhere' }}><Mono>{vialLabels(shipped ? line.shipped : line.reserved)}</Mono></TableCell>
    </TableRow>
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
            <LineRow key={line.public_id} line={line} shipped={shipped} />
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

function findingItem(f: Finding) {
  return (
    <Typography component="li" key={`${f.code}-${f.line ?? 'request'}`} data-code={f.code} sx={{ overflowWrap: 'anywhere' }}>
      {f.sentence}
    </Typography>
  )
}

function FindingGroup({ title, findings }: { title: string; findings: Finding[] }) {
  if (findings.length === 0) return null
  return (
    <>
      <Typography component="h3" variant="subtitle1" sx={{ fontWeight: 'bold' }}>
        {title}
      </Typography>
      <Box component="ul" aria-label={title} sx={{ pl: 3, my: 0 }}>
        {findings.map(findingItem)}
      </Box>
    </>
  )
}

function Findings({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) return <Typography>Nothing stands in the way: a curator may approve it.</Typography>
  return (
    <>
      <FindingGroup title="Blocks the approval" findings={findings.filter((f) => f.severity === 'block')} />
      <FindingGroup title="Needs a manager’s approval" findings={findings.filter((f) => f.severity === 'manager')} />
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

function AnswerDownload({ labId, line, role }: { labId: string; line: Line; role: Role }) {
  const document = line.depositor_answer?.document
  if (!canManage(role) || !document) return null
  return (
    <>
      {' '}
      <a href={safeHref(fileHref(labId, document.public_id))} download>
        Download the depositor’s answer for {strainName(line)}
      </a>
    </>
  )
}

const strainName = (line: Line) => line.strain.accession_number ?? line.strain.taxon

function AnswerItem({ labId, line, role, use }: { labId: string; line: Line; role: Role; use: string }) {
  const a = line.depositor_answer
  const strain = strainName(line)
  return (
    <Typography component="li" sx={{ overflowWrap: 'anywhere' }}>
      {a === null ? (
        `${strain}: the terms allow ${use} only on request to the depositor. No answer is recorded yet.`
      ) : (
        <>
          {strain}: the depositor {a.agreed ? 'agreed to' : 'declined'} {use} (answer of {a.answered_on}, recorded by {a.recorded_by} on {day(a.recorded_at)}){a.note ? `: ${a.note}` : '.'}
          <AnswerDownload labId={labId} line={line} role={role} />
        </>
      )}
    </Typography>
  )
}

/**
 * Each strain whose terms leave the use on request to the depositor (#144), with the answer once
 * recorded: yes or no, the day, the note, who recorded it, and the file for those who may open it.
 */
function Answers({ labId, request, role }: { labId: string; request: Request; role: Role }) {
  const use = USE_LABELS[request.use].toLowerCase()
  return (
    <Box component="ul" aria-label="Depositor’s answers" sx={{ pl: 3, my: 0 }}>
      {request.lines
        .filter((l) => l.on_request)
        .map((l) => (
          <AnswerItem key={l.public_id} labId={labId} line={l} role={role} use={use} />
        ))}
    </Box>
  )
}
