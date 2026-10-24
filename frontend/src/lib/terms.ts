import type { components } from '@/api/schema'

// The words of a deposit's terms of use, shared by the deposit, the strain page and the
// requests: one copy, so a label cannot read one way on the deposit and another on the strain.

type Schemas = components['schemas']
export type Use = Schemas['Use']
export type Decision = Schemas['Decision']
export type AbsScope = Schemas['AbsScope']

/** ADR 0008, D10, in the order the server lists them. To be confirmed with the curators. */
export const USES = [
  'research_noncommercial',
  'research_commercial',
  'teaching',
  'diagnostics',
  'production',
  'reference_qc',
  'patent_deposit_related',
  'redistribution',
] as const satisfies readonly Use[]
export const USE_LABELS: Record<Use, string> = {
  research_noncommercial: 'Non-commercial research',
  research_commercial: 'Commercial research',
  teaching: 'Teaching',
  diagnostics: 'Diagnostics',
  production: 'Production',
  reference_qc: 'Reference material and quality control',
  patent_deposit_related: 'Related to a patent deposit',
  redistribution: 'Redistribution to third parties',
}
export const DECISION_LABELS: Record<Decision, string> = {
  permit: 'Permitted',
  deny: 'Not permitted',
  on_request: 'On request to the depositor',
}
export const ABS_SCOPE_LABELS: Record<AbsScope, string> = {
  not_in_scope: 'Not in scope',
  in_scope: 'In scope',
  unknown: 'Unknown',
}
