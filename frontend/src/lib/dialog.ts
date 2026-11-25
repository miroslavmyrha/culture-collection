import { useRef, useState } from 'react'
import { type FocusReturn, rememberFocus } from './focus'

/**
 * The one dialog a screen has open, with the focus going back where it came from (#67). The
 * trigger is remembered when the dialog opens: the action may take its row and the button with
 * it, and rememberFocus then finds the control in the next row or the section's heading.
 * `open` stays true while the dialog shows and false while it fades out; `exited` puts the focus
 * back and ends the slot, so a dialog stays mounted until its transition ran.
 */
export function useDialogSlot<S extends { open: boolean }>() {
  const [slot, setSlot] = useState<S | null>(null)
  const spot = useRef<FocusReturn | null>(null)
  const openFrom = (control: HTMLElement, next: S) => {
    spot.current = rememberFocus(control)
    setSlot(next)
  }
  const close = () => setSlot((current) => current && { ...current, open: false })
  const exited = () => {
    spot.current?.restore()
    spot.current = null
    setSlot(null)
  }
  return { slot, openFrom, close, exited }
}
