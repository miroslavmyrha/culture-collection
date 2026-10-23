import { getRouteApi } from '@tanstack/react-router'
import { ShipmentDocumentView } from '@/features/distribution/components/ShipmentDocumentView'
import { LabGate } from '@/features/labs/components/LabGate'

const route = getRouteApi('/_authenticated/labs/$labId/shipment-documents/$documentId')

/** Thin: one document of a shipment, printable (#90). */
export function ShipmentDocumentPage() {
  const { labId, documentId } = route.useParams()
  return (
    <section>
      <LabGate labId={labId}>{() => <ShipmentDocumentView labId={labId} documentId={documentId} />}</LabGate>
    </section>
  )
}
