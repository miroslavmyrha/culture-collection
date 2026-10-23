import { LoadError } from '@/components/LoadError'
import { Box, Button, Link, PageTitle, Stack, Typography } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { safeHref } from '@/lib/safe'
import { useShipmentDocument } from '../api/queries'
import { documentDownloadHref, documentTitle } from '../schemas'

type Props = { labId: string; documentId: string }

/**
 * One document of a shipment as it was sent (#90): the text stored when the shipment was written,
 * never rendered again, with its SHA-256. A printable page: on paper only the document shows.
 * Only curators and managers read it (it names the responsible person); for others the server
 * answers 404, which reads as not found. The document never changes, so its query never refreshes.
 */
export function ShipmentDocumentView({ labId, documentId }: Props) {
  const document = useShipmentDocument(labId, documentId)
  if (document.data === undefined) {
    if (document.isPending)
      return (
        <>
          <PageTitle>Loading the document</PageTitle>
          <Typography>Loading the document…</Typography>
        </>
      )
    if (isApiError(document.error, 404))
      return (
        <>
          <PageTitle>Document not found</PageTitle>
          <Typography component="h1" variant="h4" gutterBottom>
            Document not found
          </Typography>
          <Typography>The document does not exist, or your role does not open the documents of a shipment.</Typography>
        </>
      )
    return (
      <>
        <PageTitle>Could not load the document</PageTitle>
        <LoadError what="the document" error={document.error} onRetry={() => void document.refetch()} />
      </>
    )
  }
  const d = document.data
  const title = `${documentTitle(d)}, request ${d.request_number}`
  return (
    <>
      <PageTitle>{title}</PageTitle>
      <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', mb: 2, displayPrint: 'none' }}>
        <Link to="/labs/$labId/requests/$requestId" params={{ labId, requestId: d.request }}>
          Back to request {d.request_number}
        </Link>
      </Stack>
      <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
        {title}
      </Typography>
      <Typography sx={{ mb: 2, overflowWrap: 'anywhere' }}>
        Kept as sent. SHA-256 <code>{d.text_sha256}</code>
      </Typography>
      <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', alignItems: 'center', mb: 3, displayPrint: 'none' }}>
        <Button variant="contained" onClick={() => window.print()}>
          Print
        </Button>
        <a href={safeHref(documentDownloadHref(labId, d.public_id))} download>
          Download as text
        </a>
      </Stack>
      <Box
        component="pre"
        aria-label="Document text"
        sx={{
          m: 0,
          p: 2,
          border: 1,
          borderColor: 'divider',
          borderRadius: 1,
          whiteSpace: 'pre-wrap',
          overflowWrap: 'anywhere',
          fontFamily: 'monospace',
          fontSize: '0.875rem',
          '@media print': { border: 0, p: 0, fontSize: '10pt', color: '#000' },
        }}
      >
        {d.text}
      </Box>
    </>
  )
}
