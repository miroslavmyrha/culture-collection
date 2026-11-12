import { getRouteApi } from '@tanstack/react-router'
import { LoadError } from '@/components/LoadError'
import { Link, PageTitle, Typography } from '@/components/ui'
import { useMtaTemplate } from '@/features/deposits/api/queries'
import { PublishMtaForm } from '@/features/deposits/components/PublishMtaForm'
import { canPublishMta } from '@/features/deposits/schemas'
import { LabGate } from '@/features/labs/components/LabGate'

const route = getRouteApi('/_authenticated/labs/$labId/mta-templates/new')

type BodyProps = {
  labId: string
  role: Parameters<typeof canPublishMta>[0]
  from: string | undefined
  source: ReturnType<typeof useMtaTemplate>
  onPublished: (template: { public_id: string }) => void
}

/** The form to publish a version, or the wait, the load error or the refusal that stands in for it. */
function PublishBody({ labId, role, from, source, onPublished }: BodyProps) {
  if (!canPublishMta(role)) return <Typography>Only managers publish MTA versions.</Typography>
  if (from && source.isPending) return <Typography>Loading the version to start from…</Typography>
  if (from && source.data === undefined) return <LoadError what="the version to start from" error={source.error} onRetry={() => void source.refetch()} />
  return <PublishMtaForm labId={labId} from={source.data} onPublished={onPublished} />
}

export function MtaTemplateNewPage() {
  const { labId } = route.useParams()
  const { from } = route.useSearch()
  const navigate = route.useNavigate()
  const source = useMtaTemplate(labId, from)
  return (
    <section>
      <LabGate labId={labId}>
        {(lab) => (
          <>
            <PageTitle>{`Publish an MTA version in ${lab.name}`}</PageTitle>
            <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
              Publish an MTA version in {lab.name}
            </Typography>
            <Typography sx={{ mb: 3 }}>
              <Link to="/labs/$labId/mta-templates" params={{ labId }}>
                Back to the MTA templates
              </Link>
            </Typography>
            <PublishBody
              labId={labId}
              role={lab.my_role}
              from={from}
              source={source}
              onPublished={(template) => void navigate({ to: '/labs/$labId/mta-templates/$templateId', params: { labId, templateId: template.public_id } })}
            />
          </>
        )}
      </LabGate>
    </section>
  )
}
