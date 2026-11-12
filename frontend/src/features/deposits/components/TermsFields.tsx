import { useWatch } from 'react-hook-form'
import { Stack } from '@/components/ui'
import { useMtaList } from '../api/queries'
import { USES } from '../schemas'
import { AbsFields, MatUsesFieldset, MtaField, ReferenceFields, UsesFieldset, useTerms } from './TermsGroups'

/** Every server field of the terms, for applyServerErrors: the uses by their place in USES. */
export const TERMS_FIELDS = [
  'terms.mta',
  'terms.abs_scope',
  'terms.country_of_origin',
  'terms.collection_date',
  'terms.pic_reference',
  'terms.mat_reference',
  'terms.ircc',
  'terms.permit_reference',
  'terms.uses',
  ...USES.map((_, i) => `terms.uses.${i}.decision` as const),
  'terms.mat_uses',
] as const

/**
 * The terms of a deposit inside a form that has them under `terms` (FormProvider): a decision
 * for every use (nothing is preset), the MTA version, and the ABS facts of Regulation (EU)
 * No 511/2014, Art. 4(3).
 */
export function TermsFields({ labId }: { labId: string }) {
  const { control } = useTerms()
  const mtas = useMtaList(labId)
  const scope = useWatch({ control, name: 'terms.abs_scope' })
  return (
    <Stack spacing={2}>
      <UsesFieldset />
      <MtaField mtas={mtas} />
      <AbsFields />
      <ReferenceFields inScope={scope === 'in_scope'} />
      <MatUsesFieldset inScope={scope === 'in_scope'} />
    </Stack>
  )
}
