import { useId, useMemo } from 'react'
import { useFormContext } from 'react-hook-form'
import { Box, CheckboxField, SelectField, Stack, TextField, Typography } from '@/components/ui'
import { countryOptions } from '@/lib/countries'
import type { useMtaList } from '../api/queries'
import { ABS_SCOPE_LABELS, ABS_SCOPES, DECISION_LABELS, DECISIONS, mtaLabel, options, type TermsForm, USE_LABELS, USES } from '../schemas'

const CHOOSE = { value: '', label: 'Choose' }
const DECISION_OPTIONS = [CHOOSE, ...options(DECISION_LABELS, DECISIONS)]
const SCOPE_OPTIONS = [CHOOSE, ...options(ABS_SCOPE_LABELS, ABS_SCOPES)]
const FIELDSET_SX = { border: 1, borderColor: 'divider', borderRadius: 1, p: 2, m: 0, minWidth: 0 } as const

/** The terms form context: the register function, the control and the terms' errors, which every group reads. */
export function useTerms() {
  const { register, control, formState } = useFormContext<{ terms: TermsForm }>()
  return { register, control, errors: formState.errors.terms }
}

/** An error line under a group, or nothing. */
function FieldError({ message }: { message: string | undefined }) {
  if (!message) return null
  return <Typography color="error">{message}</Typography>
}

/** A decision for every use, as the depositor agreed. Nothing is preset. */
export function UsesFieldset() {
  const { register, errors } = useTerms()
  const uses = errors?.uses
  return (
    <Box component="fieldset" sx={FIELDSET_SX}>
      <Typography component="legend" sx={{ px: 1 }}>
        Uses
      </Typography>
      <Typography sx={{ mb: 2 }}>What the material may be used for, as the depositor agreed. Decide each one.</Typography>
      <Stack spacing={2}>
        {USES.map((use, i) => (
          <SelectField key={use} label={USE_LABELS[use]} options={DECISION_OPTIONS} error={uses?.[i]?.decision?.message} {...register(`terms.uses.${i}.decision`)} />
        ))}
      </Stack>
      <FieldError message={uses?.message} />
    </Box>
  )
}

/** What the MTA field says of its list: it failed, it holds only the first versions, or the usual hint. */
function mtaHint(list: { count: number; results: readonly unknown[] } | undefined): string {
  if (list === undefined) return 'The MTA templates could not be loaded.'
  const hint = 'The agreement version the depositor signed, if any.'
  return list.count > list.results.length ? `${hint} Only the first ${list.results.length} of ${list.count} versions are listed.` : hint
}

/**
 * The MTA version. Mounted once the versions are loaded: a native select keeps its value only if
 * the option exists when it registers, so a version to start from would show as none.
 */
export function MtaField({ mtas }: { mtas: ReturnType<typeof useMtaList> }) {
  const { register, errors } = useTerms()
  if (mtas.isPending) return <Typography>Loading the MTA templates…</Typography>
  const mtaOptions = [{ value: '', label: 'No MTA' }, ...(mtas.data?.results ?? []).map((t) => ({ value: t.public_id, label: mtaLabel(t) }))]
  return <SelectField label="MTA" hint={mtaHint(mtas.data)} options={mtaOptions} error={errors?.mta?.message} {...register('terms.mta')} />
}

/** The ABS scope, the country the material was accessed in, and the collection date. */
export function AbsFields() {
  const { register, errors } = useTerms()
  const countries = useMemo(() => countryOptions(), [])
  return (
    <>
      <SelectField
        label="ABS scope"
        hint="Whether Regulation (EU) No 511/2014 applies to the material."
        options={SCOPE_OPTIONS}
        error={errors?.abs_scope?.message}
        {...register('terms.abs_scope')}
      />
      <SelectField label="Country of origin" hint="Where the material was accessed." options={countries} error={errors?.country_of_origin?.message} {...register('terms.country_of_origin')} />
      <TextField label="Collection date" hint="YYYY, YYYY-MM or YYYY-MM-DD, as far as known" autoComplete="off" error={errors?.collection_date?.message} {...register('terms.collection_date')} />
    </>
  )
}

const IRCC_HINT = { true: 'The certificate of compliance in the ABS Clearing-House. In scope needs it or a permit.', false: 'The certificate of compliance in the ABS Clearing-House, if any.' }

/** The IRCC, the permit, and the PIC and MAT references. In scope the IRCC hint says it is needed. */
export function ReferenceFields({ inScope }: { inScope: boolean }) {
  const { register, errors } = useTerms()
  return (
    <>
      <TextField label="IRCC" hint={IRCC_HINT[`${inScope}`]} autoComplete="off" error={errors?.ircc?.message} {...register('terms.ircc')} />
      <TextField label="Permit reference" hint="The access permit, when there is no IRCC." autoComplete="off" error={errors?.permit_reference?.message} {...register('terms.permit_reference')} />
      <TextField label="PIC reference" hint="Prior informed consent." autoComplete="off" error={errors?.pic_reference?.message} {...register('terms.pic_reference')} />
      <TextField label="MAT reference" hint="Mutually agreed terms." autoComplete="off" error={errors?.mat_reference?.message} {...register('terms.mat_reference')} />
    </>
  )
}

/** The uses the MAT covers, asked only for material in scope of the regulation. */
export function MatUsesFieldset({ inScope }: { inScope: boolean }) {
  const { register, errors } = useTerms()
  const hintId = useId()
  if (!inScope) return null
  return (
    <Box component="fieldset" aria-describedby={hintId} sx={FIELDSET_SX}>
      <Typography component="legend" sx={{ px: 1 }}>
        Uses the MAT covers
      </Typography>
      <Typography id={hintId}>
        What a recipient may use the material for under the mutually agreed terms. None ticked: the MAT lets nothing go to a third party, and no request is approved.
      </Typography>
      <Stack>
        {USES.map((use) => (
          <CheckboxField key={use} label={USE_LABELS[use]} value={use} {...register('terms.mat_uses')} />
        ))}
      </Stack>
      <FieldError message={errors?.mat_uses?.message} />
    </Box>
  )
}
