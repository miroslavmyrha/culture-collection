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
      <MediaTable media={media} canManage={canManage} show={show} />
      <MediaDialogs labId={labId} open={open} onClose={close} onExited={exited} />
    </>
  )
}

type Show = (kind: 'new' | 'edit' | 'retire', medium?: Medium) => (event: MouseEvent<HTMLButtonElement>) => void

/** Retired since when, or active. */
function MediumStatus({ medium }: { medium: Medium }) {
  if (medium.retired_at) return <StatusChip tone="neutral">{`Retired ${new Date(medium.retired_at).toLocaleDateString('sv')}`}</StatusChip>
  return <StatusChip>Active</StatusChip>
}

/** Edit and Retire: a retired medium keeps neither. */
function MediumActions({ medium, show }: { medium: Medium; show: Show }) {
  if (medium.retired_at !== null) return null
  return (
    <>
      <Button onClick={show('edit', medium)} aria-label={`Edit medium ${medium.name}`}>
        Edit
      </Button>
      <Button onClick={show('retire', medium)} aria-label={`Retire medium ${medium.name}`}>
        Retire
      </Button>
    </>
  )
}

/** One medium: its name, where its recipe is, its status, and the actions for those who manage. */
function MediumRow({ medium, canManage, show }: { medium: Medium; canManage: boolean; show: Show }) {
  return (
    <TableRow>
      <TableCell sx={{ overflowWrap: 'anywhere' }}>{medium.name}</TableCell>
      <TableCell sx={{ overflowWrap: 'anywhere' }}>{medium.composition_reference || 'None'}</TableCell>
      <TableCell sx={{ whiteSpace: 'nowrap' }}>
        <MediumStatus medium={medium} />
      </TableCell>
      {canManage && (
        <TableCell sx={{ whiteSpace: 'nowrap' }}>
          <MediumActions medium={medium} show={show} />
        </TableCell>
      )}
    </TableRow>
  )
}

/** The media in a table, or the words that there is none. */
function MediaTable({ media, canManage, show }: { media: readonly Medium[]; canManage: boolean; show: Show }) {
  if (media.length === 0) return <Typography>The lab has no medium yet.</Typography>
  return (
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
            <MediumRow key={m.public_id} medium={m} canManage={canManage} show={show} />
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

type DialogsProps = { labId: string; open: Open; onClose: () => void; onExited: () => void }

/** The dialog the person opened: add, edit or retire. */
function MediaDialogs({ labId, open, onClose, onExited }: DialogsProps) {
  if (open === null) return null
  if (open.kind === 'new') return <MediumDialog labId={labId} open={open.open} onClose={onClose} onExited={onExited} />
  if (open.medium === undefined) return null
  if (open.kind === 'edit') return <MediumDialog labId={labId} medium={open.medium} open={open.open} onClose={onClose} onExited={onExited} />
  return <RetireMediumDialog labId={labId} medium={open.medium} open={open.open} onClose={onClose} onExited={onExited} />
}
