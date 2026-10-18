import { Link, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { useLabList } from '../api/queries'
import { type PageParams, ROLE_LABELS } from '../schemas'
import { LoadError } from '@/components/LoadError'
import { Pager, PastTheEnd } from '@/components/Pager'

type Props = {
  params: PageParams
  /** The page owns the URL: it turns a new offset into a navigation. */
  onOffsetChange: (offset: number) => void
}

export function LabList({ params, onOffsetChange }: Props) {
  const list = useLabList(params)
  if (list.isPending) return <Typography>Loading your labs…</Typography>
  if (list.isError) return <LoadError what="your labs" error={list.error} onRetry={() => void list.refetch()} />
  const { count, results } = list.data
  if (count === 0) return <Typography>You are not a member of any lab yet. Staff add new labs and their first manager.</Typography>
  if (results.length === 0) return <PastTheEnd onFirstPage={() => onOffsetChange(0)} />
  return (
    <section aria-label="Your labs" aria-busy={list.isPlaceholderData}>
      <TableContainer component={Paper} variant="outlined">
        <Table aria-label="Your labs">
          <TableHead>
            <TableRow>
              <TableCell>Lab</TableCell>
              <TableCell>Code</TableCell>
              <TableCell>Your role</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {results.map((lab) => (
              <TableRow key={lab.public_id}>
                <TableCell>
                  <Link to="/labs/$labId" params={{ labId: lab.public_id }}>
                    {lab.name}
                  </Link>
                </TableCell>
                <TableCell>{lab.code}</TableCell>
                <TableCell>{ROLE_LABELS[lab.my_role]}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      <Pager label="Lab pages" count={count} shown={results.length} {...params} loading={list.isPlaceholderData} onOffsetChange={onOffsetChange} />
    </section>
  )
}
