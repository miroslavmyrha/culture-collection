import type { MouseEvent } from 'react'
import { LoadError } from '@/components/LoadError'
import { StaleNotice } from '@/components/StaleNotice'
import { Box, Button, Typography } from '@/components/ui'
import { growthText, noGrowth } from '@/lib/growth'
import type { usePassages } from '../api/queries'
import { type Passage, type PassageNode, passageTree, sourceLabel } from '../schemas'
import { MaterialSection } from './MaterialSection'

type Subculture = (p: Passage) => (event: MouseEvent<HTMLButtonElement>) => void

type Props = {
  passages: ReturnType<typeof usePassages>
  /** Undefined for a person who may not handle the material: no Subculture button then. */
  subculture: Subculture | undefined
}

/** The strain's passages as a tree from the deposit, or why there is none to show. */
export function PassagesSection({ passages, subculture }: Props) {
  return (
    <MaterialSection title="Passages">
      <StaleNotice what="the passages" query={passages} />
      <PassagesBody passages={passages} subculture={subculture} />
    </MaterialSection>
  )
}

function PassagesBody({ passages, subculture }: Props) {
  if (passages.isPending) return <Typography>Loading the passages…</Typography>
  if (passages.data === undefined) return <LoadError what="the passages" error={passages.error} onRetry={() => void passages.refetch()} />
  const rows = passages.data.results
  if (rows.length === 0) return <Typography>No passage yet. A strain gets passage 0 when its deposit is accepted.</Typography>
  return (
    <>
      {passages.data.count > rows.length && (
        <Typography>
          The first {rows.length} of {passages.data.count} passages.
        </Typography>
      )}
      <Box component="ul" aria-label="Passages from the deposit" sx={{ listStyle: 'none', m: 0, p: 0 }}>
        {passageTree(rows).map((node) => (
          <PassageItem key={node.passage.public_id} node={node} passages={rows} subculture={subculture} />
        ))}
      </Box>
    </>
  )
}

type PassageItemProps = {
  node: PassageNode
  passages: readonly Passage[]
  subculture: Subculture | undefined
}

/** One passage and, nested under it, the passages grown or revived from it: plain lists, no tree widget. */
function PassageItem({ node, passages, subculture }: PassageItemProps) {
  const p = node.passage
  return (
    <Box component="li" aria-label={`Passage ${p.number}`}>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', columnGap: 1, minHeight: 32 }}>
        <Typography component="span" sx={{ fontWeight: 600 }}>
          Passage {p.number}
        </Typography>
        <Typography component="span" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>
          {sourceLabel(p, passages)}
        </Typography>
        {subculture && (
          <Button size="small" aria-label={`Subculture passage ${p.number}`} onClick={subculture(p)}>
            Subculture
          </Button>
        )}
      </Box>
      {!noGrowth(p.growth) && (
        <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>
          Grown on: {growthText(p.growth)}
        </Typography>
      )}
      {node.children.length > 0 && (
        <Box component="ul" aria-label={`Grown from passage ${p.number}`} sx={{ listStyle: 'none', m: 0, pl: { xs: 1.5, sm: 3 }, ml: 1, borderLeft: 1, borderColor: 'divider' }}>
          {node.children.map((child) => (
            <PassageItem key={child.passage.public_id} node={child} passages={passages} subculture={subculture} />
          ))}
        </Box>
      )}
    </Box>
  )
}
