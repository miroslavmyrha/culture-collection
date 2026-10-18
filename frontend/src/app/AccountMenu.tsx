import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import { type Ref, useId, useState } from 'react'

type Props = {
  username: string
  /** Sign-out runs: the item stays, a second press does nothing. */
  pending: boolean
  onSignOut: () => void
  /** The menu button, for the shell to return focus to. */
  ref?: Ref<HTMLButtonElement>
}

/**
 * The signed-in user and Sign out on a narrow screen, as a WAI-ARIA menu button. The button is
 * named "Account (<username>)" and shows the username, so speech input can say what it sees.
 * MUI Menu brings the menu half of the pattern (@mui/material 9.5.0): focus on the first item
 * when it opens, arrow keys, Home, End and typeahead through MenuList, Escape and Tab close it,
 * and the Modal under it returns focus to the button. The button half is ours: aria-haspopup,
 * aria-expanded, aria-controls, and ArrowDown opening it as Enter and Space do.
 */
export function AccountMenu({ username, pending, onSignOut, ref }: Props) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const buttonId = useId()
  const menuId = useId()
  const open = anchor !== null
  return (
    <>
      <Button
        ref={ref}
        id={buttonId}
        color="inherit"
        variant="outlined"
        aria-label={`Account (${username})`}
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
        // A long username is cut off with an ellipsis here; the accessible name keeps all of it.
        sx={{ minWidth: 0, maxWidth: '100%', textTransform: 'none' }}
      >
        <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {username}
        </Box>
      </Button>
      {/* The id on the list: Menu's own id lands on the popover root, not on role="menu". */}
      <Menu anchorEl={anchor} open={open} onClose={() => setAnchor(null)} slotProps={{ list: { id: menuId, 'aria-labelledby': buttonId } }}>
        <MenuItem
          aria-disabled={pending}
          onClick={() => {
            setAnchor(null)
            onSignOut()
          }}
        >
          Sign out
        </MenuItem>
      </Menu>
    </>
  )
}
