import { Box, CheckboxField, SelectField, TextField, Typography } from '@/components/ui'
import type { FieldErrors, UseFormRegister } from 'react-hook-form'
import { useId } from 'react'
import type { useWitnesses } from '../api/queries'
import { DESTRUCTION_METHOD_LABELS, type DestructionForm, type DestructionRules } from '../schemas'

type Form = { register: UseFormRegister<DestructionForm>; errors: FieldErrors<DestructionForm> }

const METHOD_OPTIONS = Object.entries(DESTRUCTION_METHOD_LABELS).map(([value, label]) => ({ value, label }))

/** What the vials list says beneath it: the error, a cut list, or that all are chosen. */
function vialsHint(error: string | undefined, more: boolean): string {
  if (error !== undefined) return error
  return more ? 'Only the first vials marked to destroy are listed: record the rest in another record.' : 'The vials marked to destroy, all chosen.'
}

type VialsProps = Form & {
  vials: readonly { public_id: string; label: string }[]
  /** The strain has more vials to destroy than one answer lists. */
  more: boolean
}

/** The vials marked to destroy, each a box to tick, all ticked to begin with. */
export function VialsFieldset({ vials, more, register, errors }: VialsProps) {
  const hintId = useId()
  return (
    <Box component="fieldset" aria-describedby={hintId} sx={{ border: 0, m: 0, p: 0 }}>
      <Typography component="legend" sx={{ fontWeight: 600 }}>
        Vials destroyed
      </Typography>
      {vials.map((v, i) => (
        <CheckboxField
          key={v.public_id}
          label={v.label}
          value={v.public_id}
          // oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog)
          autoFocus={i === 0}
          {...register('vials')}
        />
      ))}
      <Typography id={hintId} variant="body2" color={errors.vials ? 'error' : 'text.secondary'}>
        {vialsHint(errors.vials?.message, more)}
      </Typography>
    </Box>
  )
}

/** How the vials were destroyed and how it was verified. A quarantine pest names the permit's method; a regulated strain must verify. */
export function MethodFields({ rules, register, errors }: Form & { rules: DestructionRules }) {
  const methodHint = rules.declaredMethod ? "A quarantine pest: the method the lab's ÚKZÚZ permit declares." : undefined
  const verified = rules.verification ? 'Required: the strain is regulated.' : 'Optional.'
  return (
    <>
      <SelectField label="Method" hint={methodHint} options={METHOD_OPTIONS} error={errors.method?.message} {...register('method')} />
      <TextField label="Method details" hint="The cycle or procedure, for example 121 °C, 20 min. Required for Other." autoComplete="off" error={errors.method_detail?.message} {...register('method_detail')} />
      <TextField
        label="Verification of the inactivation"
        hint={`${verified} The indicator and its result, or the cycle printout. Name no person.`}
        autoComplete="off"
        error={errors.verification?.message}
        {...register('verification')}
      />
    </>
  )
}

/** The member who witnessed the destruction of a VRAT, once the members are loaded. */
export function WitnessField({ witnesses, register, errors }: Form & { witnesses: ReturnType<typeof useWitnesses> }) {
  if (witnesses.data === undefined) return <Typography>{witnesses.isError ? 'The members could not be loaded. Close this and try again.' : 'Loading the members…'}</Typography>
  return (
    <SelectField
      label="Witness"
      hint="A highly risky agent (VRAT): the member present at the destruction, not you, and on the lab's VRAT access list on that day."
      options={[{ value: '', label: 'Choose a member' }, ...witnesses.data.map(({ value, label }) => ({ value, label }))]}
      error={errors.witness?.message}
      {...register('witness')}
    />
  )
}

/** The outside firm that took the vials: its name, the handover document, and whether the lab inactivated them first. */
export function OutsideFields({ register, errors }: Form) {
  const note = errors.inactivated_in_lab?.message
  return (
    <>
      <TextField label="Firm" hint="Its name and company number." autoComplete="off" error={errors.contractor?.message} {...register('contractor')} />
      <TextField label="Handover document" hint="The number of the document the firm signed." autoComplete="off" error={errors.handover_document?.message} {...register('handover_document')} />
      <Box>
        <CheckboxField label="Inactivated in the lab before the handover" {...register('inactivated_in_lab')} />
        {note && (
          <Typography variant="body2" color="error">
            {note}
          </Typography>
        )}
      </Box>
    </>
  )
}
