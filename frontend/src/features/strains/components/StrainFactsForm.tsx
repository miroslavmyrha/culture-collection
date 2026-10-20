import { zodResolver } from '@hookform/resolvers/zod'
import { useMemo, useRef, useState } from 'react'
import { type Path, useController, useFieldArray, useForm, useWatch } from 'react-hook-form'
import { Alert, Box, Button, SelectField, Stack, TextField, Typography } from '@/components/ui'
import { isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import type { components } from '@/api/schema'
import { countryOptions } from '@/lib/countries'
import {
  type CountryCode,
  type StrainFactsForm as Values,
  type StrainFactsValues,
  strainFactsSchema,
  emptyRestriction,
  GMO_CATEGORIES,
  GMO_CATEGORY_LABELS,
  options,
  PATHOGENICITY_LABELS,
  REFERENCE_HINTS,
  RESTRICTION_KINDS,
  RESTRICTION_LABELS,
  restrictionBody,
} from '../schemas'
import { PERMIT_REFUSED_BY_KIND, problemField, RISK_GROUP_4_REFUSED, strainError } from '../strainErrors'
import { TaxonField } from './TaxonField'

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
  'animal_pathogenicity',
  'plant_pathogenicity',
  'isolation_source',
  'country_of_origin',
  'isolation_date',
  'restrictions',
] as const satisfies readonly Path<Values>[]
const RESTRICTION_FIELDS = ['kind', 'reference', 'act', 'gmo_category'] as const

const PATHOGENICITY = options(PATHOGENICITY_LABELS, ['unknown', 'none_known', 'pathogenic'])
const RISK_GROUP_OPTIONS = [
  { value: '', label: 'Choose' },
  ...['1', '2', '3', '4'].map((value) => ({ value, label: value })),
]
const KIND_OPTIONS = options(RESTRICTION_LABELS, RESTRICTION_KINDS)
const CATEGORY_OPTIONS = [{ value: '', label: 'Choose' }, ...GMO_CATEGORIES.map((value) => ({ value: String(value), label: GMO_CATEGORY_LABELS[value] ?? '' }))]

const today = () => new Date().toLocaleDateString('sv') // YYYY-MM-DD in local time

/**
 * For curators: what the check of a deposit found, which the new strain takes. The server
 * numbers the strain ("MYC 42") and it is active at once. A risk group 4 agent and a VRAT or
 * quarantine pest without the lab's permit are refused by the server; the refusal lands on
 * the field it is about, focused.
 */
export function StrainFactsForm({ label, submitLabel, nameAsReceived, submit, onDone, country = '' }: Props) {
  const [failure, setFailure] = useState<string>()
  const addButton = useRef<HTMLButtonElement>(null)
  const countries = useMemo(() => countryOptions(), [])
  const { control, register, handleSubmit, formState, setError } = useForm<Values, unknown, StrainFactsValues>({
    resolver: zodResolver(strainFactsSchema),
    defaultValues: {
      taxon: null,
      identified_on: today(),
      identification_method: '',
      risk_group: '',
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
  const { field: taxonController } = useController({ control, name: 'taxon' })
  const { value: taxon, onChange: onTaxonChange, onBlur: onTaxonBlur, name: taxonName, ref: taxonRef } = taxonController
  const restrictions = useFieldArray({ control, name: 'restrictions' })
  const kinds = useWatch({ control, name: 'restrictions' })
  const errors = formState.errors

  const onSubmit = handleSubmit((values) => {
    if (submit.isPending) return // aria-disabled keeps focus on the button, so guard here
    setFailure(undefined)
    if (!values.taxon) return // the schema refused it already
    submit.mutate(
      {
        taxon: values.taxon.public_id,
        identified_on: values.identified_on,
        identification_method: values.identification_method.trim(),
        risk_group: values.risk_group,
        animal_pathogenicity: values.animal_pathogenicity,
        plant_pathogenicity: values.plant_pathogenicity,
        isolation_source: values.isolation_source.trim(),
        country_of_origin: values.country_of_origin,
        isolation_date: values.isolation_date.trim(),
        restrictions: values.restrictions.map(restrictionBody),
      },
      {
        onSuccess: () => onDone?.(),
        onError: (error) => {
          // Refusals the form owns, on the field they are about, never in the server's words.
          if (isApiError(error) && error.code === 'risk_group_4_refused') {
            setError('risk_group', { type: 'server', message: RISK_GROUP_4_REFUSED }, { shouldFocus: true })
            return
          }
          const nested = values.restrictions.flatMap((_, i) => RESTRICTION_FIELDS.map((name) => `restrictions.${i}.${name}` as const))
          const field = nested.find((name) => name === problemField(error))
          if (isApiError(error, 422) && error.code === 'lab_authorisation_required' && field) {
            const kind = values.restrictions[Number(field.split('.')[1])]?.kind ?? ''
            const message = PERMIT_REFUSED_BY_KIND[kind] ?? strainError(error)
            setError(field, { type: 'server', message }, { shouldFocus: true })
            return
          }
          if (!applyServerErrors(error, [...FIELDS, ...nested], setError)) setFailure(strainError(error))
        },
      },
    )
  })
  const message = errors.root?.server?.message ?? failure

  return (
    <Box component="form" onSubmit={onSubmit} noValidate aria-label={label}>
      <Stack spacing={2} sx={{ maxWidth: 640 }}>
        <Typography component="h3" variant="h6">
          Identity
        </Typography>
        <TaxonField
          label="Taxon"
          hint="Type part of the name, then choose."
          error={errors.taxon?.message}
          value={taxon ?? null}
          onChange={onTaxonChange}
          onBlur={onTaxonBlur}
          name={taxonName}
          ref={taxonRef}
        />
        <Typography>
          Name as received: <b>{nameAsReceived}</b>. The strain keeps it as the depositor gave it.
        </Typography>
        <TextField label="Identified on" hint="YYYY-MM-DD" autoComplete="off" error={errors.identified_on?.message} {...register('identified_on')} />
        <TextField
          label="Identification method"
          hint="For example 16S rRNA gene sequence or MALDI-TOF MS. Name no person."
          autoComplete="off"
          error={errors.identification_method?.message}
          {...register('identification_method')}
        />

        <Typography component="h3" variant="h6">
          Biosafety
        </Typography>
        <SelectField
          label="Risk group"
          hint="For humans, nařízení vlády 361/2007 Sb. The collection holds groups 1 to 3."
          options={RISK_GROUP_OPTIONS}
          error={errors.risk_group?.message}
          {...register('risk_group')}
        />
        <SelectField label="Animal pathogenicity" options={PATHOGENICITY} error={errors.animal_pathogenicity?.message} {...register('animal_pathogenicity')} />
        <SelectField label="Plant pathogenicity" options={PATHOGENICITY} error={errors.plant_pathogenicity?.message} {...register('plant_pathogenicity')} />

        <Typography component="h3" variant="h6">
          Origin
        </Typography>
        <TextField
          label="Isolation source"
          hint="The substrate or host, for example garden soil. Name no person."
          autoComplete="off"
          error={errors.isolation_source?.message}
          {...register('isolation_source')}
        />
        <SelectField label="Country of origin" options={countries} error={errors.country_of_origin?.message} {...register('country_of_origin')} />
        <TextField
          label="Isolation date"
          hint="YYYY, YYYY-MM or YYYY-MM-DD, as far as known"
          autoComplete="off"
          error={errors.isolation_date?.message}
          {...register('isolation_date')}
        />

        <Typography component="h3" variant="h6" id="restrictions-heading">
          Restrictions
        </Typography>
        <Typography>Every regulatory list the agent is on. A strain on none needs nothing here.</Typography>
        {restrictions.fields.map((row, index) => {
          const kind = kinds[index]?.kind ?? row.kind
          const rowErrors = errors.restrictions?.[index]
          const number = index + 1
          return (
            <Box key={row.id} component="fieldset" sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 2, m: 0, minWidth: 0 }}>
              <Typography component="legend" sx={{ px: 1 }}>
                Restriction {number}
              </Typography>
              <Stack spacing={2}>
                <SelectField label="Kind" options={KIND_OPTIONS} error={rowErrors?.kind?.message} {...register(`restrictions.${index}.kind`)} />
                <TextField
                  label="List entry"
                  hint={REFERENCE_HINTS[kind]}
                  autoComplete="off"
                  error={rowErrors?.reference?.message}
                  {...register(`restrictions.${index}.reference`)}
                />
                {kind === 'dual_use' && (
                  <TextField
                    label="Act Annex I was read in"
                    hint="The delegated act that replaced Annex I, for example (EU) 2025/2003"
                    autoComplete="off"
                    error={rowErrors?.act?.message}
                    {...register(`restrictions.${index}.act`)}
                  />
                )}
                {kind === 'gmo' && (
                  <SelectField
                    label="Contained use category"
                    hint="Act 78/2004 Sb., § 15"
                    options={CATEGORY_OPTIONS}
                    error={rowErrors?.gmo_category?.message}
                    {...register(`restrictions.${index}.gmo_category`)}
                  />
                )}
                <Box>
                  <Button
                    onClick={() => {
                      restrictions.remove(index)
                      // The button goes with its row: focus moves to the one that adds rows.
                      addButton.current?.focus()
                    }}
                  >
                    Remove restriction {number}
                  </Button>
                </Box>
              </Stack>
            </Box>
          )
        })}
        {errors.restrictions?.message && <Typography color="error">{errors.restrictions.message}</Typography>}
        <Box>
          {/* aria-disabled and a guard: at ten rows a disabled button would drop the focus. */}
          <Button
            ref={addButton}
            aria-disabled={restrictions.fields.length >= 10}
            onClick={() => {
              if (restrictions.fields.length < 10) restrictions.append({ ...emptyRestriction })
            }}
          >
            Add a restriction
          </Button>
        </Box>

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
