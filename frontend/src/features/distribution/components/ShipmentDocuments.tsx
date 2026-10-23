import { Box, Link, Typography } from '@/components/ui'
import { safeHref } from '@/lib/safe'
import { canReadDocuments, documentDownloadHref, documentTitle, type Role, shortSha, type ShipmentDocumentBrief } from '../schemas'

type Props = { labId: string; documents: ShipmentDocumentBrief[]; role: Role }

/**
 * The documents written with a shipment (#90), each with its SHA-256 in short (the full one is on
 * the document). Everyone in the lab sees which exist; curators and managers open them, as they
 * name the responsible person: a printable view and a download of the text as it was sent.
 */
export function ShipmentDocuments({ labId, documents, role }: Props) {
  if (documents.length === 0) return <Typography>This shipment was recorded before its documents were written by the app.</Typography>
  const read = canReadDocuments(role)
  return (
    <>
      {!read && <Typography>Curators and managers open the documents: they name the responsible person.</Typography>}
      <Box component="ul" aria-label="Documents of the shipment" sx={{ pl: 3, my: 0 }}>
        {documents.map((d) => {
          const title = documentTitle(d)
          return (
            <Typography component="li" key={d.public_id} sx={{ overflowWrap: 'anywhere' }}>
              {title}, SHA-256 <code title={d.text_sha256}>{shortSha(d.text_sha256)}</code>
              {read && (
                <>
                  {' '}
                  <Link to="/labs/$labId/shipment-documents/$documentId" params={{ labId, documentId: d.public_id }} aria-label={`View and print: ${title}`}>
                    View and print
                  </Link>{' '}
                  <a href={safeHref(documentDownloadHref(labId, d.public_id))} download aria-label={`Download: ${title}`}>
                    Download
                  </a>
                </>
              )}
            </Typography>
          )
        })}
      </Box>
    </>
  )
}
