import type { ReactNode } from 'react'
import { Box, Link, Typography } from '@/components/ui'
import type { Unit } from '../schemas'

type Props = { labId: string; labName: string; unit: Unit }

/** Where the unit is, as breadcrumbs from the lab's storage, and its name as the page heading. */
export function UnitHeader({ labId, labName, unit: u }: Props) {
  return (
    <>
      <Box component="nav" aria-label="Breadcrumb" sx={{ mb: 2 }}>
        <Box component="ol" sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, listStyle: 'none', m: 0, p: 0 }}>
          <Crumb>
            <Link to="/labs/$labId/storage" params={{ labId }}>
              Storage of {labName}
            </Link>
          </Crumb>
          {u.ancestors.map((a) => (
            <Crumb key={a.public_id}>
              <Link to="/labs/$labId/storage/$unitId" params={{ labId, unitId: a.public_id }}>
                {a.name}
              </Link>
            </Crumb>
          ))}
          <Crumb current>{u.name}</Crumb>
        </Box>
      </Box>
      <Typography component="h1" variant="h4" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
        {u.name}
      </Typography>
    </>
  )
}

function Crumb({ children, current = false }: { children: ReactNode; current?: boolean }) {
  return (
    <Box component="li" aria-current={current ? 'page' : undefined} sx={{ display: 'flex', gap: 1, overflowWrap: 'anywhere' }}>
      {children}
      {!current && (
        <Box component="span" aria-hidden sx={{ color: 'text.secondary' }}>
          /
        </Box>
      )}
    </Box>
  )
}
