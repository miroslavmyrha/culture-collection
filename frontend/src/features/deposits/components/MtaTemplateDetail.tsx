import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Link, PageTitle, Paper, Typography } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { useMtaTemplate } from '../api/queries'

type Props = { labId: string; templateId: string; canPublish: boolean }

/** One frozen MTA version: its text as stored and the SHA-256 that identifies it. */
export function MtaTemplateDetail({ labId, templateId, canPublish }: Props) {
  const template = useMtaTemplate(labId, templateId)
  if (template.data === undefined) {
    if (template.isPending)
      return (
        <>
          <PageTitle>Loading the MTA</PageTitle>
          <Typography>Loading the MTA…</Typography>
        </>
      )
    if (isApiError(template.error, 404))
      return (
        <>
          <PageTitle>MTA not found</PageTitle>
          <Typography component="h1" variant="h4" gutterBottom>
            MTA not found
          </Typography>
          <Typography>The MTA does not exist, or it is not in this lab.</Typography>
        </>
      )
    return (
      <>
        <PageTitle>Could not load the MTA</PageTitle>
        <LoadError what="the MTA" error={template.error} onRetry={() => void template.refetch()} />
      </>
    )
  }
  const t = template.data
  const heading = `${t.code} version ${t.version}`
  return (
    <>
      <PageTitle>{heading}</PageTitle>
      <Typography component="h1" variant="h4" gutterBottom>
        {heading}
      </Typography>
      <StaleNotice what="the MTA" query={template} />
      <Typography sx={{ mb: 1, overflowWrap: 'anywhere' }}>{t.title}</Typography>
      <Typography sx={{ mb: 2 }}>
        Published {new Date(t.created_at).toLocaleDateString('sv')}. SHA-256 of the text:{' '}
        <Box component="code" sx={{ overflowWrap: 'anywhere' }}>
          {t.text_sha256}
        </Box>
      </Typography>
      {canPublish && (
        <Link to="/labs/$labId/mta-templates/new" params={{ labId }} search={{ from: t.public_id }}>
          Publish a new version of {t.code}
        </Link>
      )}
      <Paper variant="outlined" sx={{ p: 2, mt: 2 }}>
        <Typography component="h2" variant="h6" gutterBottom>
          Text
        </Typography>
        <Typography sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{t.text}</Typography>
      </Paper>
    </>
  )
}
