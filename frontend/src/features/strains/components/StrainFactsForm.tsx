import { zodResolver } from '@hookform/resolvers/zod'
import { useRef, useState } from 'react'
import { type Path, type UseFormSetError, useController, useFieldArray, useForm, useWatch } from 'react-hook-form'
import { Alert, Box, Button, Stack } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import type { components } from '@/api/schema'
import { type CountryCode, type StrainFactsForm as Values, type StrainFactsValues, strainFactsSchema, restrictionBody } from '../schemas'
import { PERMIT_REFUSED_BY_KIND, problemField, RISK_GROUP_4_REFUSED, strainError } from '../strainErrors'
import { BiosafetyFields, IdentityFields, OriginFields, RestrictionFields } from './StrainFactsFields'

export type StrainFactsBody = components['schemas']['StrainFactsInputRequest']

/** The mutation that sends the facts: the page passes it in (deposit acceptance today). */
type Submit = {
  mutate: (body: StrainFactsBody, options: { onSuccess: () => void; onError: (error: Error) => void }) => void
  isPending: boolean
}

type Props = {
  /** The form's accessible name. */
  label: string
  submitLabel: string
  /** The deposit's name as received, which the strain takes unchanged. */
  nameAsReceived: string
  submit: Submit
  /** After the server took it. */
  onDone?: () => void
  /** The country of origin the deposit's terms state, offered as the strain's. */
  country?: CountryCode | ''
}

const FIELDS = [
  'taxon',
  'identified_on',
  'identification_method',
  'risk_group',
  'risk_group_basis',
  'animal_pathogenicity',
  'plant_pathogenicity',
  'isolation_source',
  'country_of_origin',
  'isolation_date',
  'restrictions',
] as const satisfies readonly Path<Values>[]
const RESTRICTION_FIELDS = ['kind', 'reference', 'act', 'gmo_category'] as const

const today = () => new Date().toLocaleDateString('sv') // YYYY-MM-DD in local time

/**
 * For curators: what the check of a deposit found, which the new strain takes. The server
 * numbers the strain ("MYC 42") and it is active at once. A risk group 4 agent and a VRAT or
 * quarantine pest without the lab's permit are refused by the server; the refusal lands on
 * the field it is about, focused.
 */
/** The facts as the API takes them; the taxon is chosen, the schema refused the form without one. */
function factsBody(values: StrainFactsValues, taxon: string): StrainFactsBody {
  return {
    taxon,
    identified_on: values.identified_on,
    identification_method: values.identification_method.trim(),
    risk_group: values.risk_group,
    risk_group_basis: values.risk_group_basis.trim(),
    animal_pathogenicity: values.animal_pathogenicity,
    plant_pathogenicity: values.plant_pathogenicity,
    isolation_source: values.isolation_source.trim(),
    country_of_origin: values.country_of_origin,
    isolation_date: values.isolation_date.trim(),
    restrictions: values.restrictions.map(restrictionBody),
  }
}

/** A refused permit lands on the restriction's own field, in the form's words for its kind. */
function permitRefusal(error: unknown, restrictions: StrainFactsValues['restrictions'], nested: readonly Path<Values>[], setError: UseFormSetError<Values>): boolean {
  const field = nested.find((name) => name === problemField(error))
  if (!field || !isApiError(error, 422) || error.code !== 'lab_authorisation_required') return false
  const kind = restrictions[Number(field.split('.')[1])]?.kind ?? ''
  const message = PERMIT_REFUSED_BY_KIND[kind] ?? strainError(error)
  setError(field, { type: 'server', message }, { shouldFocus: true })
  return true
}

/**
 * Refusals the form owns go on the field they are about, never in the server's words. Returns
 * the message for the form when no field took the failure.
 */
function placeFailure(error: unknown, restrictions: StrainFactsValues['restrictions'], setError: UseFormSetError<Values>): string | undefined {
  if (isApiError(error) && error.code === 'risk_group_4_refused') {
    setError('risk_group', { type: 'server', message: RISK_GROUP_4_REFUSED }, { shouldFocus: true })
    return undefined
  }
  const nested = restrictions.flatMap((_, i) => RESTRICTION_FIELDS.map((name) => `restrictions.${i}.${name}` as const))
  if (permitRefusal(error, restrictions, nested, setError)) return undefined
  return applyServerErrors(error, [...FIELDS, ...nested], setError) ? undefined : strainError(error)
}

/**
 * For curators: what the check of a deposit found, which the new strain takes. The server
 * numbers the strain ("MYC 42") and it is active at once. A risk group 4 agent and a VRAT or
 * quarantine pest without the lab's permit are refused by the server; the refusal lands on
 * the field it is about, focused.
 */
export function StrainFactsForm({ label, submitLabel, nameAsReceived, submit, onDone, country = '' }: Props) {
  const [failure, setFailure] = useState<string>()
  const addButton = useRef<HTMLButtonElement>(null)
  const { control, register, handleSubmit, formState, setError } = useForm<Values, unknown, StrainFactsValues>({
    resolver: zodResolver(strainFactsSchema),
    defaultValues: {
      taxon: null,
      identified_on: today(),
      identification_method: '',
      risk_group: '',
      risk_group_basis: '',
      animal_pathogenicity: 'unknown',
      plant_pathogenicity: 'unknown',
      isolation_source: '',
      country_of_origin: country,
      isolation_date: '',
      restrictions: [],
    },
  })
  // Before every register() of the JSX below: react-hook-form focuses the first invalid field
  // in the order fields registered, and the taxon comes first on the form.
  const { field: taxon } = useController({ control, name: 'taxon' })
  const restrictions = useFieldArray({ control, name: 'restrictions' })
  const kinds = useWatch({ control, name: 'restrictions' })
  const errors = formState.errors

  const onSubmit = handleSubmit((values) => {
    if (submit.isPending) return // aria-disabled keeps focus on the button, so guard here
    setFailure(undefined)
    if (!values.taxon) return // the schema refused it already
    submit.mutate(factsBody(values, values.taxon.public_id), {
      onSuccess: () => onDone?.(),
      onError: (error) => setFailure(placeFailure(error, values.restrictions, setError)),
    })
  })
  const message = errors.root?.server?.message ?? failure

  return (
    <Box component="form" onSubmit={onSubmit} noValidate aria-label={label}>
      <Stack spacing={2} sx={{ maxWidth: 640 }}>
        <IdentityFields nameAsReceived={nameAsReceived} taxon={taxon} register={register} errors={errors} />
        <BiosafetyFields register={register} errors={errors} />
        <OriginFields register={register} errors={errors} />
        <RestrictionFields rows={restrictions} kinds={kinds} addButton={addButton} onRemoved={() => addButton.current?.focus()} register={register} errors={errors} />

        {message && <Alert severity="error">{message}</Alert>}
        <Box>
          <Button type="submit" variant="contained" aria-disabled={submit.isPending}>
            {submitLabel}
          </Button>
        </Box>
      </Stack>
    </Box>
  )
}
