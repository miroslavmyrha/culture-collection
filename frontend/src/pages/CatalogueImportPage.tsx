import { getRouteApi } from '@tanstack/react-router'
import { PageTitle, Typography } from '@/components/ui'
import { CatalogueImport } from '@/features/catalogue/components/CatalogueImport'
import { LabGate } from '@/features/labs/components/LabGate'
import { canImportCatalogue } from '@/lib/roles'

const route = getRouteApi('/_authenticated/labs/$labId/catalogue-import')

export function CatalogueImportPage() {
  const { labId } = route.useParams()
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`Import a catalogue into ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              Import a catalogue into {lab.name}
            </Typography>
            {canImportCatalogue(lab.my_role) ? <CatalogueImport labId={labId} /> : <Typography>Only managers import a catalogue.</Typography>}
          </>
        )}
      </LabGate>
    </section>
  )
}
