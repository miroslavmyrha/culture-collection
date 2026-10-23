import type { ReactNode } from 'react'
import { Box, Link, Mono, Paper, Typography } from '@/components/ui'
import { batchSummary, type MyLab, ROLE_LABELS } from '../schemas'

/**
 * One compact card per lab: the role and the lab's figures as the role may see them. A figure
 * links to the list it counts where one exists; the counts the role may not see are absent.
 */
export function MyLabs({ labs }: { labs: MyLab[] }) {
  return (
    <Box component="section" aria-labelledby="labs-heading" sx={{ mb: 4 }}>
      <Typography id="labs-heading" component="h2" variant="h5" sx={{ mb: 1.5 }}>
        My labs
      </Typography>
      {labs.length === 0 ? (
        <Typography>You are not a member of any lab yet. Staff add new labs and their first manager.</Typography>
      ) : (
        <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0, display: 'grid', gap: 2, gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 280px), 1fr))' }}>
          {labs.map((lab) => (
            <Box component="li" key={lab.public_id}>
              <LabCard lab={lab} />
            </Box>
          ))}
        </Box>
      )}
    </Box>
  )
}

function LabCard({ lab }: { lab: MyLab }) {
  const labId = lab.public_id
  const id = `lab-${labId}`
  return (
    <Paper variant="outlined" component="article" aria-labelledby={id} sx={{ p: 2, height: '100%' }}>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', columnGap: 1, mb: 1 }}>
        <Typography id={id} component="h3" variant="h6">
          <Link to="/labs/$labId" params={{ labId }}>
            {lab.name}
          </Link>
        </Typography>
        <Typography component="span" variant="body2" color="text.secondary">
          <Mono>{lab.code}</Mono> · {ROLE_LABELS[lab.role]}
        </Typography>
      </Box>
      <Box component="dl" sx={{ m: 0, display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 2, rowGap: 0.25, '& dt': { color: 'text.secondary', display: 'flex', alignItems: 'center', minHeight: 24 }, '& dd': { m: 0, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', textAlign: 'right', fontVariantNumeric: 'tabular-nums' } }}>
        <Figure label="Strains">
          <Link to="/labs/$labId/strains" params={{ labId }} aria-label={`Strains: ${lab.strains}`} sx={figureLink}>
            {lab.strains}
          </Link>
        </Figure>
        <Figure label="Batches">{batchSummary(lab.batches)}</Figure>
        <Figure label="Vials available">{lab.vials_available}</Figure>
        <Figure label="Free box positions">
          <Link to="/labs/$labId/storage" params={{ labId }} aria-label={`Free box positions: ${lab.free_positions}`} sx={figureLink}>
            {lab.free_positions}
          </Link>
        </Figure>
        <Figure label="Open requests">
          <Link to="/labs/$labId/requests" params={{ labId }} aria-label={`Open requests: ${lab.open_requests}`} sx={figureLink}>
            {lab.open_requests}
          </Link>
        </Figure>
        {lab.requests_to_decide !== null && (
          <Figure label="Requests to decide">
            <Link to="/labs/$labId/requests" params={{ labId }} search={{ status: 'submitted' }} aria-label={`Requests to decide: ${lab.requests_to_decide}`} sx={figureLink}>
              {lab.requests_to_decide}
            </Link>
          </Figure>
        )}
        {lab.deposits_to_check !== null && (
          <Figure label="Deposits to check">
            <Link to="/labs/$labId/deposits" params={{ labId }} aria-label={`Deposits to check: ${lab.deposits_to_check}`} sx={figureLink}>
              {lab.deposits_to_check}
            </Link>
          </Figure>
        )}
      </Box>
    </Paper>
  )
}

// A figure's link is a target of 24 by 24 px at least (WCAG 2.5.8): the numbers stand close.
const figureLink = { display: 'inline-flex', alignItems: 'center', justifyContent: 'flex-end', minWidth: 24, minHeight: 24 } as const

function Figure({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <Typography component="dt" variant="body2">
        {label}
      </Typography>
      <Typography component="dd" variant="body2">
        {children}
      </Typography>
    </>
  )
}
