import Button from '@mui/material/Button'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import { useId, useState } from 'react'

export type ActionItem = {
  label: string
  /** Runs once the menu closed. The menu button is given, for the dialog to return focus to. */
  onSelect: (button: HTMLButtonElement) => void
}

type Props = {
  /** The visible text of the button. */
  label: string
  /** The button's accessible name: starts with the visible label (WCAG 2.5.3), names what it acts on. */
  name: string
  items: readonly ActionItem[]
  size?: 'small' | 'medium'
}

/**
 * Actions on one thing (a strain, a vial in a row) behind one button, as a WAI-ARIA menu button.
 * MUI Menu brings the menu half (@mui/material 9.5.0): focus on the first item, arrow keys, Home,
 * End, typeahead, Escape and Tab close it, and focus goes back to the button. The button half is
 * ours: aria-haspopup, aria-expanded, aria-controls, and ArrowDown opening it as Enter and Space
 * do. An item closes the menu before it runs, so a dialog it opens takes the focus after the
 * menu returned it to the button, and gives it back there when it closes.
 */
export function ActionMenu({ label, name, items, size = 'medium' }: Props) {
  const [anchor, setAnchor] = useState<HTMLButtonElement | null>(null)
  const open = anchor !== null
  const buttonId = useId()
  const menuId = useId()
  return (
    <>
      <Button
        id={buttonId}
        size={size}
        variant="outlined"
        aria-label={name}
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
        sx={{ whiteSpace: 'nowrap' }}
      >
        {label}
      </Button>
      {/* The id on the list: Menu's own id lands on the popover root, not on role="menu". */}
      <Menu
        anchorEl={anchor}
        open={open}
        onClose={() => setAnchor(null)}
        slotProps={{ list: { id: menuId, 'aria-labelledby': buttonId } }}
      >
        {items.map((item) => (
          <MenuItem
            key={item.label}
            onClick={() => {
              setAnchor(null)
              if (anchor) item.onSelect(anchor)
            }}
          >
            {item.label}
          </MenuItem>
        ))}
      </Menu>
    </>
  )
}
