import { Box, Typography } from '@/components/ui'
import { countsText, degrees, KIND_LABELS, sizeLabel, STATUS_LABELS, type Unit } from '../schemas'

type Row = [string, string | null]

/** "2, its own" or "1, set by Freezer A": the cap that holds and where it comes from. */
function riskCap(u: Unit): string {
  if (u.max_risk_group !== null && u.max_risk_group === u.effective_max_risk_group) return `${u.max_risk_group}`
  if (u.max_risk_group !== null) return `${u.effective_max_risk_group}, lower above it than its own ${u.max_risk_group}`
  return `${u.effective_max_risk_group}, set above it`
}

function statusText(u: Unit): string {
  const notActiveAbove = u.status === 'active' && !u.path_active
  return STATUS_LABELS[u.status] + (notActiveAbove ? ', but a unit holding it is not' : '')
}

function sizeText(u: Unit): string | null {
  return u.rows === null || u.cols === null ? null : sizeLabel(u.rows, u.cols)
}

/** The facts of a unit in reading order; a fact the unit does not have is null and left out. */
function factRows(u: Unit): Row[] {
  return [
    ['Kind', KIND_LABELS[u.kind]],
    ['Status', statusText(u)],
    ['Slot', u.slot === null ? null : String(u.slot)],
    ['Size', sizeText(u)],
    ['Box type', u.box_type ? u.box_type.name : null],
    ['Temperature', u.temperature_c === null ? null : degrees(u.temperature_c)],
    ['Highest risk group', riskCap(u)],
    // With everything below it: the impact of a failure, room for new vials (#80).
    ['Contents', countsText(u.kind, u.counts)],
    ['Barcode', u.barcode ?? 'None'],
  ]
}

/** What the unit is: a list of its facts. */
export function UnitFacts({ unit }: { unit: Unit }) {
  const rows = factRows(unit).filter((row): row is [string, string] => row[1] !== null)
  return (
    <Box component="dl" sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'max-content 1fr' }, columnGap: 3, rowGap: 1, m: 0 }}>
      {rows.map(([label, value]) => (
        <Box key={label} sx={{ display: 'contents' }}>
          <Typography component="dt" sx={{ fontWeight: 'bold' }}>
            {label}
          </Typography>
          <Typography component="dd" sx={{ m: 0, overflowWrap: 'anywhere' }}>
            {value}
          </Typography>
        </Box>
      ))}
    </Box>
  )
}
