import { type ReactNode } from 'react'
import { Box, Stack, Typography } from '@/components/ui'
import { useFocusReturnOnUnmount } from '@/lib/focus'
import { BASIS_LABELS, COOLANT_LABELS, PACKING_LABELS, type Preparation, type Role, type Shipment, TRANSPORT_CLASS_LABELS } from '../schemas'

/** The small parts the request page is built from: a titled section, a list of facts, a row of buttons. */

export const day = (iso: string) => new Date(iso).toLocaleDateString('sv')

export const reason = (text: string) => (text ? `: ${text}` : '.')

/** A curator or a manager may decide, record and ship. */
export const canManage = (role: Role) => role === 'curator' || role === 'manager'

/** The decision buttons go away with the decision: focus then moves to the section's heading. */
export function KeepsFocus({ children }: { children: ReactNode }) {
  const remember = useFocusReturnOnUnmount()
  return (
    <Stack spacing={2} onFocus={(event) => remember(event.target)}>
      {children}
    </Stack>
  )
}

export function ButtonRow({ children }: { children: ReactNode }) {
  return (
    <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap' }}>
      {children}
    </Stack>
  )
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Box component="section" aria-label={title} sx={{ mt: 4 }}>
      {/* tabIndex -1: where focus goes when the control that had it is gone. */}
      <Typography component="h2" variant="h6" tabIndex={-1} gutterBottom>
        {title}
      </Typography>
      <Stack spacing={2}>{children}</Stack>
    </Box>
  )
}

export function Facts({ rows }: { rows: [string, string][] }) {
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

export function ShipmentFacts({ shipment: s }: { shipment: Shipment }) {
  const people: [string, string][] = s.preparation
    ? [
        ['Prepared and classified by', `${s.classified_by} on ${day(s.classified_at)}`],
        ['Confirmed by', `${s.shipped_by} on ${day(s.shipped_at)}`],
      ]
    : [['Classified by', `${s.classified_by} on ${day(s.classified_at)}`]]
  return <PackageFacts package={s} people={people} />
}

const basisText = (s: Shipment | Preparation) => (s.basis_note ? `${BASIS_LABELS[s.classification_basis]}: ${s.basis_note}` : BASIS_LABELS[s.classification_basis])

const coolantText = (s: Shipment | Preparation) => (s.coolant ? `${COOLANT_LABELS[s.coolant]}${s.coolant_kg ? `, ${s.coolant_kg} kg` : ''}` : 'None')

// Null for a role that may not see people; empty once the person was erased.
const responsibleText = (name: string, phone: string | null) => (name ? `${name}, ${phone ?? ''}` : 'Erased contact')

/** What the shipper decided about a package, shipped or prepared, and who answers for it. */
export function PackageFacts({ package: s, people }: { package: Shipment | Preparation; people: [string, string][] }) {
  const rows: [string, string][] = [
    ['Transport class', TRANSPORT_CLASS_LABELS[s.transport_class]],
    ['Basis', basisText(s)],
    ...people,
    ['Packing', PACKING_LABELS[s.packing_instruction]],
    ['Coolant', coolantText(s)],
  ]
  if (s.responsible_name !== null) rows.push(['Responsible person', responsibleText(s.responsible_name, s.responsible_phone)])
  rows.push(['Carrier', s.carrier], ['Tracking number', s.tracking_number || 'None'])
  return <Facts rows={rows} />
}
