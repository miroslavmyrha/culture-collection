import { zodResolver } from '@hookform/resolvers/zod'
import { useId, useMemo, useState } from 'react'
import { type FieldErrors, type UseFormRegister, useForm, useWatch } from 'react-hook-form'
import { ConfirmDialog, SelectField, Stack, TextField } from '@/components/ui'
import { countryOptions, isCountry } from '@/lib/countries'
import { useAddPermit, useCreateRequester, useEndPermit, useUpdateRequester } from '../api/mutations'
import {
  type EndPermitForm,
  endPermitSchema,
  LEGAL_FORM_LABELS,
  LEGAL_FORMS,
  NAMES_AGENTS,
  options,
  type Permit,
  PERMIT_KIND_LABELS,
  PERMIT_KINDS,
  type PermitForm,
  permitSchema,
  type PermitValues,
  type Requester,
  type RequesterForm,
  requesterSchema,
  type RequesterValues,
} from '../schemas'
import { END_PERMIT_ERRORS, REQUESTER_ERRORS, submitFailure } from '../submitErrors'
import { FileField } from './RequestDialogs'

type Base = { labId: string; open: boolean; onClose: () => void; onExited: () => void }
const today = () => new Date().toLocaleDateString('sv')
const CHOOSE = { value: '', label: 'Choose' }

const REQUESTER_FIELDS = ['institution', 'legal_form', 'registration_number', 'seat', 'country', 'lab_evidence', 'lab_confirmed_on', 'name', 'email', 'postal_address'] as const

const BLANK_REQUESTER: RequesterForm = {
  institution: '',
  legal_form: '',
  registration_number: '',
  seat: '',
  country: '',
  lab_evidence: '',
  lab_confirmed_on: '',
  name: '',
  email: '',
  postal_address: '',
}

/** A new requester starts empty, confirmed today. A changed one starts as it is recorded. */
function requesterDefaults(requester: Requester | undefined): RequesterForm {
  if (!requester) return { ...BLANK_REQUESTER, lab_confirmed_on: today() }
  return {
    institution: requester.institution,
    legal_form: requester.legal_form,
    registration_number: requester.registration_number,
    seat: requester.seat,
    country: isCountry(requester.country) ? requester.country : '',
    lab_evidence: requester.lab_evidence,
    lab_confirmed_on: requester.lab_confirmed_on,
    name: requester.name,
    email: requester.email,
    postal_address: requester.postal_address,
  }
}

type CountryOptions = { value: string; label: string }[]
// The fields get their registration from the dialog on every render: a child that took the whole form could be skipped by the compiler after a reset().
type RequesterFieldsProps = { register: UseFormRegister<RequesterForm>; errors: FieldErrors<RequesterForm>; countries: CountryOptions }

function RequesterFields({ register, errors, countries }: RequesterFieldsProps) {
  return (
    <>
      {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog) */}
      <TextField label="Institution" autoFocus autoComplete="off" error={errors.institution?.message} {...register('institution')} />
      <SelectField label="Legal form" options={[CHOOSE, ...options(LEGAL_FORM_LABELS, LEGAL_FORMS)]} error={errors.legal_form?.message} {...register('legal_form')} />
      <TextField label="Company number" hint="The IČO or its equivalent, if it has one." autoComplete="off" error={errors.registration_number?.message} {...register('registration_number')} />
      <TextField label="Registered office" hint="The address of the institution in the business register. Not the delivery address." autoComplete="off" error={errors.seat?.message} {...register('seat')} />
      <SelectField label="Country" hint="Where the laboratory is: the destination of its requests." options={countries} error={errors.country?.message} {...register('country')} />
      <TextField label="How the laboratory was confirmed" hint="The page, document or call that shows a microbiology laboratory. Name no person." multiline minRows={2} error={errors.lab_evidence?.message} {...register('lab_evidence')} />
      <TextField label="Confirmed on" hint="YYYY-MM-DD" autoComplete="off" error={errors.lab_confirmed_on?.message} {...register('lab_confirmed_on')} />
      <TextField label="Responsible scientist" autoComplete="off" error={errors.name?.message} {...register('name')} />
      <TextField label="E-mail" type="email" autoComplete="off" error={errors.email?.message} {...register('email')} />
      <TextField label="Delivery address of the laboratory" multiline minRows={2} autoComplete="off" error={errors.postal_address?.message} {...register('postal_address')} />
    </>
  )
}

/**
 * Add a requester or change one: an institution, never a private person, with the evidence that
 * it has a microbiology laboratory, and its responsible scientist. The scientist and the
 * delivery address are personal data: the audit trail records only that they changed.
 */
export function RequesterDialog({ labId, requester, open, onClose, onExited }: Base & { requester?: Requester }) {
  const create = useCreateRequester(labId)
  const update = useUpdateRequester(labId, requester?.public_id ?? '')
  const save = requester ? update : create
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const countries = useMemo(() => [CHOOSE, ...countryOptions().slice(1)], [])
  const { register, handleSubmit, formState, setError } = useForm<RequesterForm, unknown, RequesterValues>({ resolver: zodResolver(requesterSchema), defaultValues: requesterDefaults(requester) })
  const errors = formState.errors
  const onSubmit = handleSubmit((values) => {
    if (save.isPending) return
    setFailure(undefined)
    save.mutate(values, { onSuccess: onClose, onError: (error) => setFailure(submitFailure(error, REQUESTER_FIELDS, setError, REQUESTER_ERRORS)) })
  })
  return (
    <ConfirmDialog
      open={open}
      title={requester ? `Change ${requester.institution}` : 'Add a requester'}
      description="Only institutions with a microbiology laboratory receive material. The responsible scientist and the delivery address are personal data."
      confirmLabel={requester ? 'Save the requester' : 'Add the requester'}
      form={formId}
      pending={save.isPending}
      error={failure ?? errors.root?.server?.message}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Requester" spacing={2} sx={{ mt: 2 }}>
        <RequesterFields register={register} errors={errors} countries={countries} />
      </Stack>
    </ConfirmDialog>
  )
}

const PERMIT_FIELDS = ['kind', 'issuer', 'issuer_country', 'reference', 'valid_from', 'expires_on', 'covers', 'endorsement_reference', 'endorsed_on', 'quantity_allowed', 'sendings_allowed', 'gmo_category', 'risk_group', 'file'] as const
const orNull = (value: string) => (value === '' ? null : Number(value))

const BLANK_PERMIT: PermitForm = {
  kind: '',
  issuer: '',
  issuer_country: '',
  reference: '',
  valid_from: '',
  expires_on: '',
  covers: '',
  endorsement_reference: '',
  endorsed_on: '',
  quantity_allowed: '',
  sendings_allowed: '',
  gmo_category: '',
  risk_group: '',
  file: null,
}

/** The issuer is most likely in the requester's own country. */
const permitDefaults = (requester: Requester): PermitForm => ({ ...BLANK_PERMIT, issuer_country: isCountry(requester.country) ? requester.country : '' })

const NO_LETTER = { endorsement_reference: '', endorsed_on: null, quantity_allowed: null, sendings_allowed: null }
/** What only a Letter of Authority carries: its endorsement with the day, and the quantity and sendings it allows. */
const letterFacts = (values: PermitValues) =>
  values.kind === 'plant_health_loa'
    ? { endorsement_reference: values.endorsement_reference, endorsed_on: values.endorsed_on || null, quantity_allowed: orNull(values.quantity_allowed), sendings_allowed: orNull(values.sendings_allowed) }
    : NO_LETTER

/** What goes to the server: the facts of the kind the permit is, and none of another kind's. */
const permitBody = (requester: Requester, values: PermitValues) => ({
  requester: requester.public_id,
  kind: values.kind,
  issuer: values.issuer,
  issuer_country: values.issuer_country,
  reference: values.reference,
  valid_from: values.valid_from,
  expires_on: values.expires_on || null,
  covers: NAMES_AGENTS.includes(values.kind) ? values.covers : '',
  ...letterFacts(values),
  gmo_category: values.kind === 'gmo_contained_use' ? orNull(values.gmo_category) : null,
  risk_group: values.kind === 'pathogen_work_permit' ? orNull(values.risk_group) : null,
})

type PermitFieldsProps = { register: UseFormRegister<PermitForm>; errors: FieldErrors<PermitForm>; countries: CountryOptions; kind: string }

/** The fields only some kinds of permit have, in the place they have on the form. */
function PermitKindFields({ register, errors, kind }: Omit<PermitFieldsProps, 'countries'>) {
  return (
    <>
      {NAMES_AGENTS.some((k) => k === kind) && (
        <TextField label="Agents or pests it names" hint="As written on the document, with their scientific names." multiline minRows={2} error={errors.covers?.message} {...register('covers')} />
      )}
      {kind === 'plant_health_loa' && (
        <>
          <TextField label="Quantity allowed" inputMode="numeric" autoComplete="off" error={errors.quantity_allowed?.message} {...register('quantity_allowed')} />
          <TextField label="Sendings allowed" inputMode="numeric" autoComplete="off" error={errors.sendings_allowed?.message} {...register('sendings_allowed')} />
          <TextField label="Endorsement by the state of origin" hint="Its reference, as on the letter. Nothing goes out on a letter with no endorsement (Regulation (EU) 2019/829, Art. 6(2))." autoComplete="off" error={errors.endorsement_reference?.message} {...register('endorsement_reference')} />
          <TextField label="Endorsed on" hint="YYYY-MM-DD, the day of the endorsement." autoComplete="off" error={errors.endorsed_on?.message} {...register('endorsed_on')} />
        </>
      )}
      {kind === 'gmo_contained_use' && <TextField label="Category" hint="1 to 4, act 78/2004 Sb." inputMode="numeric" autoComplete="off" error={errors.gmo_category?.message} {...register('gmo_category')} />}
      {kind === 'pathogen_work_permit' && <TextField label="Highest risk group" hint="1 to 4." inputMode="numeric" autoComplete="off" error={errors.risk_group?.message} {...register('risk_group')} />}
    </>
  )
}

function PermitFields({ register, errors, countries, kind }: PermitFieldsProps) {
  return (
    <>
      <SelectField label="Kind" options={[CHOOSE, ...options(PERMIT_KIND_LABELS, PERMIT_KINDS)]} error={errors.kind?.message} {...register('kind')} />
      <TextField label="Issued by" hint="The authority, as on the document." autoComplete="off" error={errors.issuer?.message} {...register('issuer')} />
      <SelectField label="Country of the issuer" options={countries} error={errors.issuer_country?.message} {...register('issuer_country')} />
      <TextField label="Reference" autoComplete="off" error={errors.reference?.message} {...register('reference')} />
      <TextField label="Valid from" hint="YYYY-MM-DD" autoComplete="off" error={errors.valid_from?.message} {...register('valid_from')} />
      <TextField label="Expires on" hint="The last valid day, YYYY-MM-DD. Empty when the document states none." autoComplete="off" error={errors.expires_on?.message} {...register('expires_on')} />
      <PermitKindFields register={register} errors={errors} kind={kind} />
      <FileField label="File of the document" error={errors.file?.message} {...register('file')} />
    </>
  )
}

/** A document the requester holds, with its file: recorded once it is in hand. */
export function PermitDialog({ labId, requester, open, onClose, onExited }: Base & { requester: Requester }) {
  const add = useAddPermit(labId)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const countries = useMemo(() => [CHOOSE, ...countryOptions().slice(1)], [])
  const { register, handleSubmit, formState, setError, control } = useForm<PermitForm, unknown, PermitValues>({ resolver: zodResolver(permitSchema), defaultValues: permitDefaults(requester) })
  const kind = useWatch({ control, name: 'kind' })
  const errors = formState.errors
  const onSubmit = handleSubmit((values) => {
    if (add.isPending) return
    setFailure(undefined)
    add.mutate({ body: permitBody(requester, values), file: values.file }, { onSuccess: onClose, onError: (error) => setFailure(submitFailure(error, PERMIT_FIELDS, setError)) })
  })
  return (
    <ConfirmDialog
      open={open}
      title={`Add a permit of ${requester.institution}`}
      description="The document with its file. A permit is never deleted: when it stops holding, end it."
      confirmLabel="Add the permit"
      form={formId}
      pending={add.isPending}
      error={failure ?? errors.root?.server?.message}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="Permit" spacing={2} sx={{ mt: 2 }}>
        <PermitFields register={register} errors={errors} countries={countries} kind={kind} />
      </Stack>
    </ConfirmDialog>
  )
}

const END_FIELDS = ['ended_on', 'reason'] as const

/** The permit stops holding from a day, with a reason. The row and its file stay. */
export function EndPermitDialog({ labId, permit, open, onClose, onExited }: Base & { permit: Permit }) {
  const end = useEndPermit(labId, permit.public_id)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const { register, handleSubmit, formState, setError } = useForm<EndPermitForm>({ resolver: zodResolver(endPermitSchema), defaultValues: { ended_on: today(), reason: '' } })
  const onSubmit = handleSubmit((values) => {
    setFailure(undefined)
    end.mutate(
      { ended_on: values.ended_on, reason: values.reason.trim() },
      {
        onSuccess: onClose,
        onError: (error) => setFailure(submitFailure(error, END_FIELDS, setError, END_PERMIT_ERRORS)),
      },
    )
  })
  return (
    <ConfirmDialog
      open={open}
      destructive
      title={`End ${permit.reference}?`}
      description="From that day the permit no longer counts for a request. It cannot be undone; a renewed permit is added as a new one."
      confirmLabel="End the permit"
      form={formId}
      pending={end.isPending}
      error={failure}
      onClose={onClose}
      onExited={onExited}
    >
      <Stack component="form" id={formId} onSubmit={onSubmit} noValidate aria-label="End of the permit" spacing={2} sx={{ mt: 2 }}>
        <TextField label="First day it no longer holds" hint="YYYY-MM-DD" autoComplete="off" error={formState.errors.ended_on?.message} {...register('ended_on')} />
        <TextField label="Reason" hint="Stored for good. Name no person." multiline minRows={2} error={formState.errors.reason?.message} {...register('reason')} />
      </Stack>
    </ConfirmDialog>
  )
}
