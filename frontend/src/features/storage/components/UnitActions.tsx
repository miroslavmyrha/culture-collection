import type { MouseEvent } from 'react'
import { Button, Stack } from '@/components/ui'
import { HOLDS, isRoot, KIND_WORDS, type Unit } from '../schemas'

/** The dialogs a unit's actions open. */
export type UnitAction = 'add' | 'edit' | 'move' | 'out_of_service' | 'active' | 'retired'

type Props = {
  unit: Unit
  canManage: boolean
  show: (action: UnitAction) => (event: MouseEvent<HTMLButtonElement>) => void
}

/** What a curator may do with the unit; a retired unit changes no more. */
export function UnitActions({ unit: u, canManage, show }: Props) {
  if (!canManage || u.status === 'retired') return null
  const holds = HOLDS[u.kind]
  return (
    <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap', my: 3 }}>
      {holds.length > 0 && u.status === 'active' && (
        <Button variant="contained" onClick={show('add')}>
          Add a {holds.map((k) => KIND_WORDS[k]).join(' or ')}
        </Button>
      )}
      <Button variant="outlined" onClick={show('edit')}>
        Change
      </Button>
      {!isRoot(u.kind) && (
        <Button variant="outlined" onClick={show('move')}>
          Move
        </Button>
      )}
      <ServiceButton active={u.status === 'active'} show={show} />
      <Button variant="outlined" color="error" onClick={show('retired')}>
        Retire
      </Button>
    </Stack>
  )
}

function ServiceButton({ active, show }: { active: boolean; show: Props['show'] }) {
  return active ? (
    <Button variant="outlined" onClick={show('out_of_service')}>
      Put out of service
    </Button>
  ) : (
    <Button variant="outlined" onClick={show('active')}>
      Put back in service
    </Button>
  )
}
