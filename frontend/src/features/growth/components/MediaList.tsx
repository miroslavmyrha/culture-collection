import { type MouseEvent, useRef, useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Button, Paper, StatusChip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@/components/ui'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { type Medium } from '@/lib/growth'
import { useMediaList } from '../api/queries'
import { MediumDialog, RetireMediumDialog } from './MediumDialogs'

type Open = { kind: 'new' | 'edit' | 'retire'; medium?: Medium; open: boolean } | null

/**
 * The lab's media (#79): active ones first, then the retired. Curators and managers add, edit
 * and retire; a medium is never deleted, because strains and passages keep pointing to it.
 */
export function MediaList({ labId, canManage }: { labId: string; canManage: boolean }) {
  const list = useMediaList(labId)
  const [open, setOpen] = useState<Open>(null)
  const spot = useRef<FocusReturn | null>(null)
  const show = (kind: 'new' | 'edit' | 'retire', medium?: Medium) => (event: MouseEvent<HTMLButtonElement>) => {
    spot.current = rememberFocus(event.currentTarget)
    setOpen({ kind, medium, open: true })
  }
  const close = () => setOpen((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setOpen(null)
  }
  if (list.data === undefined) {
    if (list.isPending) return <Typography>Loading the media…</Typography>
    return <LoadError what="the media" error={list.error} onRetry={() => void list.refetch()} />
  }
  const media = list.data.results
  return (
    <>
      <StaleNotice what="the media" query={list} />
      {canManage && (
        <Button variant="outlined" onClick={show('new')} sx={{ mb: 2 }}>
          Add a medium
        </Button>
      )}
      {list.data.count > media.length && (
        <Typography sx={{ mb: 1 }}>
          Showing the first {media.length} of {list.data.count} media.
        </Typography>
      )}
      {media.length === 0 ? (
        <Typography>The lab has no medium yet.</Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table aria-label="Media">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Composition reference</TableCell>
                <TableCell>Status</TableCell>
                {canManage && <TableCell>Action</TableCell>}
              </TableRow>
            </TableHead>
            <TableBody>
              {media.map((m) => (
                <TableRow key={m.public_id}>
                  <TableCell sx={{ overflowWrap: 'anywhere' }}>{m.name}</TableCell>
                  <TableCell sx={{ overflowWrap: 'anywhere' }}>{m.composition_reference || 'None'}</TableCell>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>
                    {m.retired_at ? (
                      <StatusChip tone="neutral">{`Retired ${new Date(m.retired_at).toLocaleDateString('sv')}`}</StatusChip>
                    ) : (
                      <StatusChip>Active</StatusChip>
                    )}
                  </TableCell>
                  {canManage && (
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>
                      {m.retired_at === null && (
                        <>
                          <Button onClick={show('edit', m)} aria-label={`Edit medium ${m.name}`}>
                            Edit
                          </Button>
                          <Button onClick={show('retire', m)} aria-label={`Retire medium ${m.name}`}>
                            Retire
                          </Button>
                        </>
                      )}
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
      {open?.kind === 'new' && <MediumDialog labId={labId} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'edit' && open.medium && <MediumDialog labId={labId} medium={open.medium} open={open.open} onClose={close} onExited={exited} />}
      {open?.kind === 'retire' && open.medium && <RetireMediumDialog labId={labId} medium={open.medium} open={open.open} onClose={close} onExited={exited} />}
    </>
  )
}
