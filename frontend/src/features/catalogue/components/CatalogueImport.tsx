import { useId, useState } from 'react'
import { Alert, Box, Button, Link, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { REASON_HINT } from '@/lib/forms'
import { safeHref } from '@/lib/safe'
import { type Checked, type Imported, refusal, templateUrl, useCheckCatalogue, useImportCatalogue } from '../api/mutations'

const MAX_MB = 2

const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? '' : 's'}`

/** A table that may scroll sideways: a named region and a tab stop, so the keys can scroll it. */
const scrollable = (name: string) => ({ component: Paper, variant: 'outlined', tabIndex: 0, role: 'region', 'aria-label': `${name} table` }) as const

/**
 * A former catalogue, moved in from a CSV file (#70): the manager downloads the template, fills
 * it in, checks it (every row tried, nothing written), then imports the file that was checked,
 * all rows or none, with a reason. Each row becomes a deposit accepted into a strain.
 */
export function CatalogueImport({ labId }: { labId: string }) {
  const [file, setFile] = useState<File | null>(null)
  const [checked, setChecked] = useState<Checked | null>(null)
  const [imported, setImported] = useState<Imported | null>(null)
  const check = useCheckCatalogue(labId)
  const apply = useImportCatalogue(labId)

  const pick = (picked: File | null) => {
    setFile(picked)
    setChecked(null)
    setImported(null)
    check.reset()
    apply.reset()
  }
  const runCheck = () => {
    if (file) check.mutate(file, { onSuccess: setChecked })
  }
  const runImport = (reason: string) => {
    if (file && checked) apply.mutate({ file, sha256: checked.sha256, reason }, { onSuccess: setImported })
  }

  return (
    <Stack spacing={3}>
      <Steps labId={labId} />
      <FileStep onPick={pick} onCheck={runCheck} ready={file !== null} pending={check.isPending} />
      <Failure error={check.error ?? apply.error} />
      {imported ? (
        <ImportResult labId={labId} imported={imported} />
      ) : (
        checked && <CheckedStep checked={checked} pending={apply.isPending} onImport={runImport} />
      )}
    </Stack>
  )
}

function Failure({ error }: { error: Error | null }) {
  return error && <Alert severity="error">{refusal(error) ?? errorMessage(error)}</Alert>
}

/** The check's answer, and the import's reason once no row fails. */
function CheckedStep({ checked, pending, onImport }: { checked: Checked; pending: boolean; onImport: (reason: string) => void }) {
  return (
    <>
      <CheckResult checked={checked} />
      {checked.row_errors.length === 0 && <ReasonStep rows={checked.rows} pending={pending} onImport={onImport} />}
    </>
  )
}

function Steps({ labId }: { labId: string }) {
  return (
    <Box component="ol" sx={{ m: 0, pl: 3 }}>
      <li>
        <Typography>
          Fill in the template, one row per strain, and save it as CSV UTF-8, at most {MAX_MB} MB. A depositor, a taxon, an MTA and a list entry must
          already exist here.
        </Typography>
        <Typography sx={{ my: 1 }}>
          <a href={safeHref(templateUrl(labId))} download="catalogue-template.csv">
            Download the template
          </a>
        </Typography>
      </li>
      <li>
        <Typography>Check the file. Nothing is written; every row with an error is listed.</Typography>
      </li>
      <li>
        <Typography>Import it with a reason. Every row is imported, or none.</Typography>
      </li>
    </Box>
  )
}

type FileStepProps = { onPick: (file: File | null) => void; onCheck: () => void; ready: boolean; pending: boolean }

function FileStep({ onPick, onCheck, ready, pending }: FileStepProps) {
  const fileId = useId()
  return (
    <Stack spacing={1} sx={{ alignItems: 'flex-start' }}>
      <Typography component="label" htmlFor={fileId}>
        Catalogue file
      </Typography>
      <input id={fileId} type="file" accept=".csv,text/csv" onChange={(event) => onPick(event.target.files?.[0] ?? null)} />
      <Button variant="contained" onClick={onCheck} disabled={!ready || pending}>
        {pending ? 'Checking…' : 'Check the file'}
      </Button>
    </Stack>
  )
}

function ReasonStep({ rows, pending, onImport }: { rows: number; pending: boolean; onImport: (reason: string) => void }) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | undefined>()
  const submit = () => {
    const missing = reason.trim() === ''
    setError(missing ? 'Give the reason for the import.' : undefined)
    if (!missing) onImport(reason)
  }
  return (
    <Stack spacing={2} sx={{ alignItems: 'flex-start', maxWidth: 640 }}>
      <TextField
        label="Reason"
        multiline
        minRows={2}
        fullWidth
        required
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        error={error}
        hint={`${REASON_HINT} It is recorded with the file's hash.`}
      />
      <Button variant="contained" onClick={submit} disabled={pending}>
        {pending ? 'Importing…' : `Import ${count(rows, 'strain')}`}
      </Button>
    </Stack>
  )
}

function CheckResult({ checked }: { checked: Checked }) {
  if (checked.row_errors.length === 0)
    return (
      // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- MUI Alert owns its root element; role="status" is what <output> would give
      <Alert severity="success" role="status">
        {checked.rows === 1 ? 'The row' : `All ${checked.rows} rows`} can be imported.
      </Alert>
    )
  return (
    <Stack spacing={1}>
      {/* oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- MUI Alert owns its root element; role="status" is what <output> would give */}
      <Alert severity="warning" role="status">
        {count(checked.row_errors.length, 'error')} in {count(checked.rows, 'row')}. Correct the file and check it again: nothing is imported while a row
        fails.
      </Alert>
      <TableContainer {...scrollable('Row errors')}>
        <Table size="small">
          <caption>Row errors, by the line of the file (the header is line 1)</caption>
          <TableHead>
            <TableRow>
              <TableCell scope="col">Line</TableCell>
              <TableCell scope="col">Column</TableCell>
              <TableCell scope="col">Error</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {checked.row_errors.map((e) => (
              <TableRow key={`${e.row}-${e.column}-${e.message}`}>
                <TableCell>{e.row}</TableCell>
                <TableCell>{e.column || 'The row'}</TableCell>
                <TableCell>{e.message}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Stack>
  )
}

function ImportResult({ labId, imported }: { labId: string; imported: Imported }) {
  const n = imported.strains.length
  return (
    <Stack spacing={1}>
      {/* oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- MUI Alert owns its root element; role="status" is what <output> would give */}
      <Alert severity="success" role="status">
        Imported {count(n, 'strain')}.
      </Alert>
      <Box component="ul" aria-label="Imported strains" sx={{ m: 0, pl: 3 }}>
        {imported.strains.map((s) => (
          <li key={s.public_id}>
            <Link to="/labs/$labId/strains/$strainId" params={{ labId, strainId: s.public_id }}>
              {s.accession_number}
            </Link>
            {s.former_number && ` (formerly ${s.former_number})`}
          </li>
        ))}
      </Box>
    </Stack>
  )
}
