import { Box, Mono, Paper, StatusChip, Typography } from '@/components/ui'
import { KIND_TITLES, type MyLab, type WaitingGroup, type WaitingItem } from '../schemas'
import { TargetLink } from './TargetLink'

/**
 * What waits for the person, one group per kind in the server's order, oldest first in each:
 * what, which lab, since when and why, each linking to the page where it is handled. The
 * server decides what a role sees; nothing here filters.
 */
export function Waiting({ groups, labs }: { groups: WaitingGroup[]; labs: MyLab[] }) {
  const codes = new Map(labs.map((lab) => [lab.public_id, lab.code]))
  const total = groups.reduce((sum, group) => sum + group.total, 0)
  return (
    <Box component="section" aria-labelledby="waiting-heading" sx={{ mb: 4 }}>
      <Typography id="waiting-heading" component="h2" variant="h5" sx={{ mb: 1.5 }}>
        Waiting for you{total > 0 ? ` (${total})` : ''}
      </Typography>
      {groups.length === 0 ? (
        <Typography>Nothing waits for you.</Typography>
      ) : (
        <Box sx={{ display: 'grid', gap: 2 }}>
          {groups.map((group) => (
            <Group key={group.kind} group={group} codes={codes} />
          ))}
        </Box>
      )}
    </Box>
  )
}

function Group({ group, codes }: { group: WaitingGroup; codes: Map<string, string> }) {
  const id = `waiting-${group.kind}`
  const hidden = group.total - group.items.length
  return (
    <Paper variant="outlined" component="section" aria-labelledby={id} sx={{ overflow: 'hidden' }}>
      <Box sx={{ px: 2, py: 1, bgcolor: 'background.default', borderBottom: 1, borderColor: 'divider' }}>
        <Typography id={id} component="h3" variant="h6">
          {KIND_TITLES[group.kind]} ({group.total})
        </Typography>
      </Box>
      <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0 }}>
        {group.items.map((item) => (
          <Item key={`${item.lab}-${item.target_id ?? ''}-${item.subject}`} item={item} code={codes.get(item.lab) ?? ''} />
        ))}
      </Box>
      {hidden > 0 && (
        <Typography variant="body2" color="text.secondary" sx={{ px: 2, py: 1, borderTop: 1, borderColor: 'divider' }}>
          The oldest {group.items.length} of {group.total} are shown.
        </Typography>
      )}
    </Paper>
  )
}

function Item({ item, code }: { item: WaitingItem; code: string }) {
  return (
    <Box component="li" sx={{ px: 2, py: 1, '& + &': { borderTop: 1, borderColor: 'divider' } }}>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', columnGap: 1, rowGap: 0.5 }}>
        <Box component="span" sx={{ fontWeight: 600, overflowWrap: 'anywhere' }}>
          <TargetLink labId={item.lab} target={item.target} id={item.target_id}>
            {item.subject}
          </TargetLink>
        </Box>
        <Typography component="span" variant="body2" color="text.secondary">
          <Mono>{code}</Mono>
        </Typography>
        {item.needs_manager && <StatusChip tone="regulated">Manager approves</StatusChip>}
        <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: { sm: 'auto' }, whiteSpace: 'nowrap' }}>
          {item.due ? `Expires ${item.due}` : `Since ${item.since}`}
        </Typography>
      </Box>
      <Typography variant="body2" color="text.secondary">
        {item.reason}
      </Typography>
    </Box>
  )
}
