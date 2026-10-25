import { useId, useMemo } from 'react'
import { useFormContext, useWatch } from 'react-hook-form'
import { Box, CheckboxField, SelectField, Stack, TextField, Typography } from '@/components/ui'
import { countryOptions } from '@/lib/countries'
import { useMtaList } from '../api/queries'
import { ABS_SCOPE_LABELS, ABS_SCOPES, DECISION_LABELS, DECISIONS, mtaLabel, options, type TermsForm, USE_LABELS, USES } from '../schemas'

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

const CHOOSE = { value: '', label: 'Choose' }
const DECISION_OPTIONS = [CHOOSE, ...options(DECISION_LABELS, DECISIONS)]
const SCOPE_OPTIONS = [CHOOSE, ...options(ABS_SCOPE_LABELS, ABS_SCOPES)]

/** What the MTA field says of its list: it failed, it holds only the first versions, or the usual hint. */
function mtaHint(list: { count: number; results: readonly unknown[] } | undefined): string {
  if (list === undefined) return 'The MTA templates could not be loaded.'
  const hint = 'The agreement version the depositor signed, if any.'
  return list.count > list.results.length ? `${hint} Only the first ${list.results.length} of ${list.count} versions are listed.` : hint
}

/**
 * The terms of a deposit inside a form that has them under `terms` (FormProvider): a decision
 * for every use (nothing is preset), the MTA version, and the ABS facts of Regulation (EU)
 * No 511/2014, Art. 4(3).
 */
export function TermsFields({ labId }: { labId: string }) {
  const { register, control, formState } = useFormContext<{ terms: TermsForm }>()
  const errors = formState.errors.terms
  const mtas = useMtaList(labId)
  const scope = useWatch({ control, name: 'terms.abs_scope' })
  const countries = useMemo(() => countryOptions(), [])
  const matHintId = useId()
  const mtaOptions = [{ value: '', label: 'No MTA' }, ...(mtas.data?.results ?? []).map((t) => ({ value: t.public_id, label: mtaLabel(t) }))]
  return (
    <Stack spacing={2}>
      <Box component="fieldset" sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 2, m: 0, minWidth: 0 }}>
        <Typography component="legend" sx={{ px: 1 }}>
          Uses
        </Typography>
        <Typography sx={{ mb: 2 }}>What the material may be used for, as the depositor agreed. Decide each one.</Typography>
        <Stack spacing={2}>
          {USES.map((use, i) => (
            <SelectField key={use} label={USE_LABELS[use]} options={DECISION_OPTIONS} error={errors?.uses?.[i]?.decision?.message} {...register(`terms.uses.${i}.decision`)} />
          ))}
        </Stack>
        {errors?.uses?.message && <Typography color="error">{errors.uses.message}</Typography>}
      </Box>
      {/* Mounted once the versions are loaded: a native select keeps its value only if the
          option exists when it registers, so a version to start from would show as none. */}
      {mtas.isPending ? (
        <Typography>Loading the MTA templates…</Typography>
      ) : (
        <SelectField
          label="MTA"
          hint={mtaHint(mtas.data)}
          options={mtaOptions}
          error={errors?.mta?.message}
          {...register('terms.mta')}
        />
      )}
      <SelectField
        label="ABS scope"
        hint="Whether Regulation (EU) No 511/2014 applies to the material."
        options={SCOPE_OPTIONS}
        error={errors?.abs_scope?.message}
        {...register('terms.abs_scope')}
      />
      <SelectField label="Country of origin" hint="Where the material was accessed." options={countries} error={errors?.country_of_origin?.message} {...register('terms.country_of_origin')} />
      <TextField label="Collection date" hint="YYYY, YYYY-MM or YYYY-MM-DD, as far as known" autoComplete="off" error={errors?.collection_date?.message} {...register('terms.collection_date')} />
      <TextField label="IRCC" hint={scope === 'in_scope' ? 'The certificate of compliance in the ABS Clearing-House. In scope needs it or a permit.' : 'The certificate of compliance in the ABS Clearing-House, if any.'} autoComplete="off" error={errors?.ircc?.message} {...register('terms.ircc')} />
      <TextField label="Permit reference" hint="The access permit, when there is no IRCC." autoComplete="off" error={errors?.permit_reference?.message} {...register('terms.permit_reference')} />
      <TextField label="PIC reference" hint="Prior informed consent." autoComplete="off" error={errors?.pic_reference?.message} {...register('terms.pic_reference')} />
      <TextField label="MAT reference" hint="Mutually agreed terms." autoComplete="off" error={errors?.mat_reference?.message} {...register('terms.mat_reference')} />
      {scope === 'in_scope' && (
        <Box component="fieldset" aria-describedby={matHintId} sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 2, m: 0, minWidth: 0 }}>
          <Typography component="legend" sx={{ px: 1 }}>
            Uses the MAT covers
          </Typography>
          <Typography id={matHintId}>
            What a recipient may use the material for under the mutually agreed terms. None ticked: the MAT lets nothing go to a third party, and no request is approved.
          </Typography>
          <Stack>
            {USES.map((use) => (
              <CheckboxField key={use} label={USE_LABELS[use]} value={use} {...register('terms.mat_uses')} />
            ))}
          </Stack>
          {errors?.mat_uses?.message && <Typography color="error">{errors.mat_uses.message}</Typography>}
        </Box>
      )}
    </Stack>
  )
}
