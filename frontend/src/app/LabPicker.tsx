import { useNavigate } from '@tanstack/react-router'
import { type KeyboardEvent, useState, useId } from 'react'
import { Box, Button } from '@/components/ui'
import Divider from '@mui/material/Divider'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import { useLab, useLabList } from '@/features/labs/api/queries'

/** The sections every member sees; where the user stands in one is kept when the lab changes. */
const KEPT_SECTIONS = ['strains', 'storage', 'requests'] as const
export type KeptSection = (typeof KEPT_SECTIONS)[number]
export const keptSection = (segment: string | undefined): KeptSection | undefined => KEPT_SECTIONS.find((section) => section === segment)

type Props = {
  /** The lab the page is in, from the URL. */
  labId: string | undefined
  /** The section of that lab the page is in: the first path segment after the lab's id. */
  section: string | undefined
}

type Navigate = ReturnType<typeof useNavigate>

/** Where picking a lab goes: the section the user is in, else the lab's own page. */
const OPEN_LAB: Record<KeptSection | 'lab', (navigate: Navigate, labId: string) => Promise<void>> = {
  strains: (navigate, labId) => navigate({ to: '/labs/$labId/strains', params: { labId } }),
  storage: (navigate, labId) => navigate({ to: '/labs/$labId/storage', params: { labId } }),
  requests: (navigate, labId) => navigate({ to: '/labs/$labId/requests', params: { labId } }),
  lab: (navigate, labId) => navigate({ to: '/labs/$labId', params: { labId } }),
}

/** The button's name: the visible words stay in it (WCAG 2.5.3). */
const buttonName = (labId: string | undefined, name: string | undefined) => (labId === undefined ? 'Select a lab' : `Lab ${name ?? 'loading'}`)

/** What the button shows. Two spans: the name algorithm joins them without a space. */
function ButtonText({ labId, name }: { labId: string | undefined; name: string | undefined }) {
  if (labId === undefined) {
    return (
      <Box component="span" sx={{ fontWeight: 600 }}>
        Select a lab
      </Box>
    )
  }
  return (
    <>
      <Box component="span" sx={{ color: 'text.secondary' }}>
        Lab
      </Box>
      <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: 600 }}>
        {name ?? '…'}
      </Box>
    </>
  )
}

/** The disabled lines the menu may need: no lab, labs that did not load. */
function LabsNote({ count, failed }: { count: number | undefined; failed: boolean }) {
  return (
    <>
      {count === 0 && (
        <MenuItem disabled aria-disabled>
          You are in no lab
        </MenuItem>
      )}
      {failed && (
        <MenuItem disabled aria-disabled>
          Could not load your labs
        </MenuItem>
      )}
    </>
  )
}

/** ArrowDown on the button opens the menu (WAI-ARIA menu button). */
function openOnArrowDown(event: KeyboardEvent<HTMLElement>, open: (anchor: HTMLElement) => void) {
  if (event.key !== 'ArrowDown') return
  event.preventDefault()
  open(event.currentTarget)
}

type LabMenuProps = {
  anchor: HTMLElement | null
  ids: { menu: string; button: string }
  labs: { public_id: string; name: string }[] | undefined
  failed: boolean
  labId: string | undefined
  onPick: (labId: string) => void
  onAll: () => void
  onClose: () => void
}

/** The menu: one radio item per lab, the notes, "All labs". */
function LabMenu({ anchor, ids, labs, failed, labId, onPick, onAll, onClose }: LabMenuProps) {
  return (
    <Menu anchorEl={anchor} open={anchor !== null} onClose={onClose} slotProps={{ list: { id: ids.menu, 'aria-labelledby': ids.button, dense: true } }}>
      {labs?.map((lab) => (
        <MenuItem key={lab.public_id} role="menuitemradio" aria-checked={lab.public_id === labId} selected={lab.public_id === labId} onClick={() => onPick(lab.public_id)}>
          {lab.name}
        </MenuItem>
      ))}
      <LabsNote count={labs?.length} failed={failed} />
      <Divider component="li" />
      <MenuItem onClick={onAll}>All labs</MenuItem>
    </Menu>
  )
}

/**
 * The lab picker of the top bar: a menu button with the user's labs (WAI-ARIA menu button, radio
 * items, the current lab checked) and "All labs". Picking a lab opens the same section of it
 * (Strains, Storage, Requests) or its page. Labs come in one page of up to 200: a user is a member
 * of a handful.
 */
export function LabPicker({ labId, section }: Props) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const buttonId = useId()
  const menuId = useId()
  const navigate = useNavigate()
  const labs = useLabList({ limit: 200, offset: 0 })
  const current = useLab(labId ?? '', labId !== undefined)
  const open = anchor !== null
  const results = labs.data?.results
  const name = current.data?.name ?? results?.find((lab) => lab.public_id === labId)?.name
  const close = () => setAnchor(null)

  return (
    <>
      <Button
        id={buttonId}
        variant="outlined"
        aria-label={buttonName(labId, name)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={(event) => setAnchor(event.currentTarget)}
        onKeyDown={(event) => openOnArrowDown(event, setAnchor)}
        sx={{ minWidth: 0, maxWidth: '100%', justifyContent: 'flex-start', gap: 0.75 }}
      >
        <ButtonText labId={labId} name={name} />
        <Box component="span" aria-hidden sx={{ fontSize: '0.7em' }}>
          ▾
        </Box>
      </Button>
      <LabMenu
        anchor={anchor}
        ids={{ menu: menuId, button: buttonId }}
        labs={results}
        failed={labs.isError}
        labId={labId}
        onPick={(id) => {
          close()
          void OPEN_LAB[keptSection(section) ?? 'lab'](navigate, id)
        }}
        onAll={() => {
          close()
          void navigate({ to: '/labs' })
        }}
        onClose={close}
      />
    </>
  )
}
