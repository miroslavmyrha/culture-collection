import { screen } from '@testing-library/react'
import type { UserEvent } from '@testing-library/user-event'

/** A vial's action from its row's menu (#19): Move, Place, Change state or Revive. */
export async function vialAction(user: UserEvent, label: string, item: 'Move' | 'Place' | 'Change state' | 'Revive') {
  await user.click(await screen.findByRole('button', { name: `Actions for vial ${label}` }, { timeout: 5000 }))
  await user.click(await screen.findByRole('menuitem', { name: item }))
}
