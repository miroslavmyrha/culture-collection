import type { MouseEvent } from 'react'
import type { Batch, BatchCheck, Passage, Vial } from '../schemas'

/** The dialog of the Material tab that is open, and whether it is still shown or fading out. */
export type Open =
  | { kind: 'preserve'; open: boolean }
  | { kind: 'subculture'; passage: Passage; open: boolean }
  | { kind: 'place' | 'status' | 'revive' | 'loss-report'; vial: Vial; open: boolean }
  | { kind: 'place-many'; vials: readonly Vial[]; open: boolean }
  | { kind: 'check'; batch: Batch; checks: readonly BatchCheck[] | undefined; open: boolean }
  | { kind: 'release' | 'hold'; batch: Batch; open: boolean }
  | { kind: 'check-error'; check: BatchCheck; open: boolean }
  | null

/** Opens a dialog from a button's click, and remembers the button for the focus on close. */
export type Show = (next: NonNullable<Open>) => (event: MouseEvent<HTMLButtonElement>) => void

/** Opens a dialog from a row's menu: the focus goes back to the menu button. */
export type ShowFrom = (next: NonNullable<Open>) => (button: HTMLButtonElement) => void

/** Opens a dialog from a control in a batch's checks panel, which the action may remove. */
export type InPanel = (headingId: string, next: NonNullable<Open>) => (event: MouseEvent<HTMLButtonElement>) => void
