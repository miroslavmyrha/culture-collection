import { zodResolver } from '@hookform/resolvers/zod'
import { useId, useMemo, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { ConfirmDialog, SelectField, Stack, TextField } from '@/components/ui'
import { errorMessage, isApiError } from '@/lib/api'
import { countryOptions, isCountry } from '@/lib/countries'
import { applyServerErrors } from '@/lib/forms'
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
import { FileField } from './RequestDialogs'

type Base = { labId: string; open: boolean; onClose: () => void; onExited: () => void }
const today = () => new Date().toLocaleDateString('sv')
const CHOOSE = { value: '', label: 'Choose' }

const REQUESTER_FIELDS = ['institution', 'legal_form', 'registration_number', 'country', 'lab_evidence', 'lab_confirmed_on', 'name', 'email', 'postal_address'] as const

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
  const { register, handleSubmit, formState, setError } = useForm<RequesterForm, unknown, RequesterValues>({
    resolver: zodResolver(requesterSchema),
    defaultValues: {
      institution: requester?.institution ?? '',
      legal_form: requester?.legal_form ?? '',
      registration_number: requester?.registration_number ?? '',
      country: requester && isCountry(requester.country) ? requester.country : '',
      lab_evidence: requester?.lab_evidence ?? '',
      lab_confirmed_on: requester?.lab_confirmed_on ?? today(),
      name: requester?.name ?? '',
      email: requester?.email ?? '',
      postal_address: requester?.postal_address ?? '',
    },
  })
  const errors = formState.errors
  const onSubmit = handleSubmit((values) => {
    if (save.isPending) return
    setFailure(undefined)
    save.mutate(
      values,
      {
        onSuccess: onClose,
        onError: (error) => {
          if (isApiError(error, 409) && error.code === 'contact_erased') setFailure('This contact was erased. The requester can no longer be changed.')
          else if (!applyServerErrors(error, REQUESTER_FIELDS, setError)) setFailure(errorMessage(error))
        },
      },
    )
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
        {/* oxlint-disable-next-line jsx-a11y/no-autofocus -- a form dialog opens on its first field (WAI-ARIA dialog) */}
        <TextField label="Institution" autoFocus autoComplete="off" error={errors.institution?.message} {...register('institution')} />
        <SelectField label="Legal form" options={[CHOOSE, ...options(LEGAL_FORM_LABELS, LEGAL_FORMS)]} error={errors.legal_form?.message} {...register('legal_form')} />
        <TextField label="Company number" hint="The IČO or its equivalent, if it has one." autoComplete="off" error={errors.registration_number?.message} {...register('registration_number')} />
        <SelectField label="Country" hint="Where the laboratory is: the destination of its requests." options={countries} error={errors.country?.message} {...register('country')} />
        <TextField label="How the laboratory was confirmed" hint="The page, document or call that shows a microbiology laboratory. Name no person." multiline minRows={2} error={errors.lab_evidence?.message} {...register('lab_evidence')} />
        <TextField label="Confirmed on" hint="YYYY-MM-DD" autoComplete="off" error={errors.lab_confirmed_on?.message} {...register('lab_confirmed_on')} />
        <TextField label="Responsible scientist" autoComplete="off" error={errors.name?.message} {...register('name')} />
        <TextField label="E-mail" type="email" autoComplete="off" error={errors.email?.message} {...register('email')} />
        <TextField label="Delivery address of the laboratory" multiline minRows={2} autoComplete="off" error={errors.postal_address?.message} {...register('postal_address')} />
      </Stack>
    </ConfirmDialog>
  )
}

const PERMIT_FIELDS = ['kind', 'issuer', 'issuer_country', 'reference', 'valid_from', 'expires_on', 'covers', 'quantity_allowed', 'sendings_allowed', 'gmo_category', 'risk_group', 'file'] as const
const orNull = (value: string) => (value === '' ? null : Number(value))

/** A document the requester holds, with its file: recorded once it is in hand. */
export function PermitDialog({ labId, requester, open, onClose, onExited }: Base & { requester: Requester }) {
  const add = useAddPermit(labId)
  const formId = useId()
  const [failure, setFailure] = useState<string>()
  const countries = useMemo(() => [CHOOSE, ...countryOptions().slice(1)], [])
  const { register, handleSubmit, formState, setError, control } = useForm<PermitForm, unknown, PermitValues>({
    resolver: zodResolver(permitSchema),
    defaultValues: {
      kind: '',
      issuer: '',
      issuer_country: isCountry(requester.country) ? requester.country : '',
      reference: '',
      valid_from: '',
      expires_on: '',
      covers: '',
      quantity_allowed: '',
      sendings_allowed: '',
      gmo_category: '',
      risk_group: '',
      file: null,
    },
  })
  const kind = useWatch({ control, name: 'kind' })
  const errors = formState.errors
  const onSubmit = handleSubmit((values) => {
    if (add.isPending) return
    setFailure(undefined)
    add.mutate(
      {
        body: {
          requester: requester.public_id,
          kind: values.kind,
          issuer: values.issuer,
          issuer_country: values.issuer_country,
          reference: values.reference,
          valid_from: values.valid_from,
          expires_on: values.expires_on || null,
          covers: NAMES_AGENTS.includes(values.kind) ? values.covers : '',
          endorsement_reference: '',
          quantity_allowed: values.kind === 'plant_health_loa' ? orNull(values.quantity_allowed) : null,
          sendings_allowed: values.kind === 'plant_health_loa' ? orNull(values.sendings_allowed) : null,
          gmo_category: values.kind === 'gmo_contained_use' ? orNull(values.gmo_category) : null,
          risk_group: values.kind === 'pathogen_work_permit' ? orNull(values.risk_group) : null,
        },
        file: values.file,
      },
      {
        onSuccess: onClose,
        onError: (error) => {
          if (!applyServerErrors(error, PERMIT_FIELDS, setError)) setFailure(errorMessage(error))
        },
      },
    )
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
        <SelectField label="Kind" options={[CHOOSE, ...options(PERMIT_KIND_LABELS, PERMIT_KINDS)]} error={errors.kind?.message} {...register('kind')} />
        <TextField label="Issued by" hint="The authority, as on the document." autoComplete="off" error={errors.issuer?.message} {...register('issuer')} />
        <SelectField label="Country of the issuer" options={countries} error={errors.issuer_country?.message} {...register('issuer_country')} />
        <TextField label="Reference" autoComplete="off" error={errors.reference?.message} {...register('reference')} />
        <TextField label="Valid from" hint="YYYY-MM-DD" autoComplete="off" error={errors.valid_from?.message} {...register('valid_from')} />
        <TextField label="Expires on" hint="The last valid day, YYYY-MM-DD. Empty when the document states none." autoComplete="off" error={errors.expires_on?.message} {...register('expires_on')} />
        {NAMES_AGENTS.some((k) => k === kind) && (
          <TextField label="Agents or pests it names" hint="As written on the document, with their scientific names." multiline minRows={2} error={errors.covers?.message} {...register('covers')} />
        )}
        {kind === 'plant_health_loa' && (
          <>
            <TextField label="Quantity allowed" inputMode="numeric" autoComplete="off" error={errors.quantity_allowed?.message} {...register('quantity_allowed')} />
            <TextField label="Sendings allowed" inputMode="numeric" autoComplete="off" error={errors.sendings_allowed?.message} {...register('sendings_allowed')} />
          </>
        )}
        {kind === 'gmo_contained_use' && <TextField label="Category" hint="1 to 4, act 78/2004 Sb." inputMode="numeric" autoComplete="off" error={errors.gmo_category?.message} {...register('gmo_category')} />}
        {kind === 'pathogen_work_permit' && <TextField label="Highest risk group" hint="1 to 4." inputMode="numeric" autoComplete="off" error={errors.risk_group?.message} {...register('risk_group')} />}
        <FileField label="File of the document" error={errors.file?.message} {...register('file')} />
      </Stack>
    </ConfirmDialog>
  )
}

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
        onError: (error) => {
          if (isApiError(error, 409) && error.code === 'permit_ended') setFailure('This permit was ended already.')
          else if (!applyServerErrors(error, ['ended_on', 'reason'], setError)) setFailure(errorMessage(error))
        },
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
