import { LoadError } from '@/components/LoadError'
import { Link, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { useMtaList } from '../api/queries'

/** Every version of every MTA of the lab, the newest of each code first. Texts are frozen. */
export function MtaTemplateList({ labId }: { labId: string }) {
  const list = useMtaList(labId)
  if (list.isPending) return <Typography>Loading the MTA templates…</Typography>
  if (list.isError) return <LoadError what="the MTA templates" error={list.error} onRetry={() => void list.refetch()} />
  if (list.data.count === 0) return <Typography>The lab has no MTA template yet.</Typography>
  return (
    <TableContainer component={Paper} variant="outlined">
      <Table aria-label="MTA templates">
        <TableHead>
          <TableRow>
            <TableCell>Code and version</TableCell>
            <TableCell>Title</TableCell>
            <TableCell>SHA-256 of the text</TableCell>
            <TableCell>Published</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {list.data.results.map((t) => (
            <TableRow key={t.public_id}>
              <TableCell sx={{ whiteSpace: 'nowrap' }}>
                <Link to="/labs/$labId/mta-templates/$templateId" params={{ labId, templateId: t.public_id }}>
                  {`${t.code} version ${t.version}`}
                </Link>
              </TableCell>
              <TableCell sx={{ overflowWrap: 'break-word' }}>{t.title}</TableCell>
              <TableCell sx={{ fontFamily: 'monospace' }}>{t.text_sha256.slice(0, 12)}…</TableCell>
              <TableCell sx={{ whiteSpace: 'nowrap' }}>{new Date(t.created_at).toLocaleDateString('sv')}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}
