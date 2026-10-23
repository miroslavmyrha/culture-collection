import { useNavigate } from '@tanstack/react-router'
import { useState, useId } from 'react'
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
  const name = current.data?.name ?? labs.data?.results.find((lab) => lab.public_id === labId)?.name
  const close = () => setAnchor(null)

  const go = (id: string) => {
    close()
    const kept = keptSection(section)
    if (kept === 'strains') void navigate({ to: '/labs/$labId/strains', params: { labId: id } })
    else if (kept === 'storage') void navigate({ to: '/labs/$labId/storage', params: { labId: id } })
    else if (kept === 'requests') void navigate({ to: '/labs/$labId/requests', params: { labId: id } })
    else void navigate({ to: '/labs/$labId', params: { labId: id } })
  }

  return (
    <>
      <Button
        id={buttonId}
        variant="outlined"
        // Two spans: the name algorithm joins them without a space. The visible words stay in the name (WCAG 2.5.3).
        aria-label={labId === undefined ? 'Select a lab' : `Lab ${name ?? 'loading'}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={(event) => setAnchor(event.currentTarget)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown') {
            event.preventDefault()
            setAnchor(event.currentTarget)
          }
        }}
        sx={{ minWidth: 0, maxWidth: '100%', justifyContent: 'flex-start', gap: 0.75 }}
      >
        {labId === undefined ? (
          <Box component="span" sx={{ fontWeight: 600 }}>
            Select a lab
          </Box>
        ) : (
          <>
            <Box component="span" sx={{ color: 'text.secondary' }}>
              Lab
            </Box>
            <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: 600 }}>
              {name ?? '…'}
            </Box>
          </>
        )}
        <Box component="span" aria-hidden sx={{ fontSize: '0.7em' }}>
          ▾
        </Box>
      </Button>
      <Menu anchorEl={anchor} open={open} onClose={close} slotProps={{ list: { id: menuId, 'aria-labelledby': buttonId, dense: true } }}>
        {labs.data?.results.map((lab) => (
          <MenuItem key={lab.public_id} role="menuitemradio" aria-checked={lab.public_id === labId} selected={lab.public_id === labId} onClick={() => go(lab.public_id)}>
            {lab.name}
          </MenuItem>
        ))}
        {labs.data?.results.length === 0 && (
          <MenuItem disabled aria-disabled>
            You are in no lab
          </MenuItem>
        )}
        {labs.isError && (
          <MenuItem disabled aria-disabled>
            Could not load your labs
          </MenuItem>
        )}
        <Divider component="li" />
        <MenuItem
          onClick={() => {
            close()
            void navigate({ to: '/labs' })
          }}
        >
          All labs
        </MenuItem>
      </Menu>
    </>
  )
}
