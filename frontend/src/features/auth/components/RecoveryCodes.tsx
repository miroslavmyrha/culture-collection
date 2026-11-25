import { useState } from 'react'
import { Alert, Button, Mono, Stack, Typography } from '@/components/ui'

/** Ten recovery codes, shown this once (#176). Each signs in once when every factor is lost. */
export function RecoveryCodes({ codes, onDone, doneLabel = 'I have saved them, continue' }: { codes: string[]; onDone: () => void; doneLabel?: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(codes.join('\n'))
    setCopied(true)
  }
  return (
    <Stack spacing={2}>
      <Typography component="h2" variant="h6">
        Your recovery codes
      </Typography>
      <Typography>
        Each code signs you in once if you lose your security key or phone. Keep them somewhere safe, away from this computer. They are not shown again.
      </Typography>
      <ol aria-label="Recovery codes">
        {codes.map((code) => (
          <li key={code}>
            <Mono>{code}</Mono>
          </li>
        ))}
      </ol>
      <Stack direction="row" spacing={1}>
        <Button variant="outlined" onClick={() => void copy()}>
          Copy the codes
        </Button>
        <Button variant="outlined" onClick={() => window.print()}>
          Print
        </Button>
      </Stack>
      {copied && (
        // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- MUI Alert owns its root element; role="status" is what <output> would give
        <Alert severity="success" role="status">
          Copied.
        </Alert>
      )}
      <Button variant="contained" onClick={onDone}>
        {doneLabel}
      </Button>
    </Stack>
  )
}
