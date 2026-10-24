import { Box, Link, Typography } from '@/components/ui'
import { ACTION_LABELS, ACTIONS, type Action, type MyLab } from '../schemas'

/**
 * What the person's roles let them start, as links to the form or the list. In one lab the
 * action is named alone; in several, once per lab with its code. A role that starts nothing (a
 * viewer) gets no section at all. Finding a vial goes to the strain list until search exists.
 */
export function QuickActions({ labs }: { labs: MyLab[] }) {
  const offered = ACTIONS.map((action) => [action, labs.filter((lab) => lab.actions.includes(action))] as const).filter(([, where]) => where.length > 0)
  if (offered.length === 0) return null
  return (
    <Box component="section" aria-labelledby="actions-heading" sx={{ mb: 4 }}>
      <Typography id="actions-heading" component="h2" variant="h5" sx={{ mb: 1.5 }}>
        Quick actions
      </Typography>
      <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0, display: 'flex', flexWrap: 'wrap', gap: 1 }}>
        {offered.flatMap(([action, where]) =>
          where.map((lab) => (
            <Box component="li" key={`${action}-${lab.public_id}`}>
              <ActionLink action={action} labId={lab.public_id}>
                {where.length > 1 ? `${ACTION_LABELS[action]} in ${lab.code}` : ACTION_LABELS[action]}
              </ActionLink>
            </Box>
          )),
        )}
      </Box>
    </Box>
  )
}

// A link that looks like a secondary button: it opens a page, so it is a link (WCAG 4.1.2).
const buttonSx = {
  display: 'inline-flex',
  alignItems: 'center',
  minHeight: 32,
  px: 1.5,
  border: 1,
  borderColor: 'controlBorder',
  borderRadius: 1,
  bgcolor: 'background.paper',
  color: 'text.primary',
  fontWeight: 500,
  '&:hover': { bgcolor: 'action.hover', borderColor: 'text.secondary' },
} as const

// Where each action starts. Finding a vial and recording a check start from the strain list
// until search exists (step 3).
const STARTS = {
  receive_deposit: '/labs/$labId/deposits/new',
  record_check: '/labs/$labId/strains',
  find_vial: '/labs/$labId/strains',
  enter_request: '/labs/$labId/requests/new',
} as const satisfies Record<Action, string>

function ActionLink({ action, labId, children }: { action: Action; labId: string; children: string }) {
  return (
    <Link to={STARTS[action]} params={{ labId }} underline="none" sx={buttonSx}>
      {children}
    </Link>
  )
}
