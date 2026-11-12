import { zodResolver } from '@hookform/resolvers/zod'
import { useRef, useState } from 'react'
import { type FieldErrors, FormProvider, useController, useForm, type UseFormRegister, useWatch } from 'react-hook-form'
import { useUnsavedGuard } from '@/components/UnsavedGuard'
import { Alert, Box, Button, SelectField, Stack, TextField, Typography } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { applyServerErrors } from '@/lib/forms'
import { useReceiveDeposit } from '../api/mutations'
import { CONDITION_LABELS, CONDITIONS, type Deposit, type Depositor, emptyTerms, options, type ReceiveForm, type ReceiveValues, receiveSchema, termsBody } from '../schemas'
import { DepositorDialog } from './DepositorDialog'
import { DepositorField } from './DepositorField'
import { TERMS_FIELDS, TermsFields } from './TermsFields'

type Props = { labId: string; onReceived: (deposit: Deposit) => void }

const FIELDS = ['depositor', 'received_on', 'condition', 'condition_note', 'name_as_received', 'depositor_passages', ...TERMS_FIELDS] as const
const today = () => new Date().toLocaleDateString('sv') // YYYY-MM-DD in local time

const defaults = (): ReceiveForm => ({
  depositor: null,
  received_on: today(),
  condition: 'intact',
  condition_note: '',
  name_as_received: '',
  depositor_passages: '',
  terms: emptyTerms(),
})

/** What the server is sent for a filled form: the depositor by id, the passages as a number or none, the terms as the API takes them. */
function receiptBody(values: ReceiveValues, depositor: Depositor) {
  return {
    depositor: depositor.public_id,
    received_on: values.received_on,
    condition: values.condition,
    condition_note: values.condition_note,
    name_as_received: values.name_as_received,
    depositor_passages: values.depositor_passages === '' ? null : Number(values.depositor_passages),
    terms: termsBody(values.terms),
  }
}

/** What the note on the condition asks for: about the material when it is intact, what was wrong otherwise. */
const NOTE_HINTS = { intact: 'Optional. About the material: name no person.', other: 'Say what was wrong with it. Name no person.' }

type ReceiptProps = { register: UseFormRegister<ReceiveForm>; errors: FieldErrors<ReceiveForm>; condition: ReceiveForm['condition'] }

/** What came and in what state: the date, the name as received, the condition and its note, the passages. */
function ReceiptFields({ register, errors, condition }: ReceiptProps) {
  return (
    <>
      <TextField label="Received on" hint="YYYY-MM-DD" autoComplete="off" error={errors.received_on?.message} {...register('received_on')} />
      <TextField label="Name as received" hint="As the depositor gave it. The strain keeps it unchanged." autoComplete="off" error={errors.name_as_received?.message} {...register('name_as_received')} />
      <SelectField label="Condition on arrival" options={options(CONDITION_LABELS, CONDITIONS)} error={errors.condition?.message} {...register('condition')} />
      <TextField
        label="Note on the condition"
        hint={NOTE_HINTS[condition === 'intact' ? 'intact' : 'other']}
        multiline
        minRows={2}
        error={errors.condition_note?.message}
        {...register('condition_note')}
      />
      <TextField label="Passages stated by the depositor" hint="Optional. How many times it was subcultured before it came." inputMode="numeric" autoComplete="off" error={errors.depositor_passages?.message} {...register('depositor_passages')} />
    </>
  )
}

/** An error line, or nothing. */
function FormError({ message }: { message: string | undefined }) {
  if (!message) return null
  return <Alert severity="error">{message}</Alert>
}

/**
 * For curators: the material arrived. One page: who deposited it, what came and in what
 * state, and the terms under which it may be used. Saving records the deposit as received,
 * with its terms as version 1; the check and the decision follow on the deposit's page.
 */
export function ReceiveDepositForm({ labId, onReceived }: Props) {
  const receive = useReceiveDeposit(labId)
  const [failure, setFailure] = useState<string>()
  const [adding, setAdding] = useState<{ open: boolean } | null>(null)
  const spot = useRef<FocusReturn | null>(null)
  const form = useForm<ReceiveForm, unknown, ReceiveValues>({ resolver: zodResolver(receiveSchema), defaultValues: defaults() })
  const { control, register, handleSubmit, formState, setError } = form
  // Before every register() below: the first invalid field focused is the first on the form.
  const { field: depositorController } = useController({ control, name: 'depositor' })
  const { value: depositor, onChange: onDepositorChange, onBlur: onDepositorBlur, name: depositorName, ref: depositorRef } = depositorController
  const condition = useWatch({ control, name: 'condition' })
  const errors = formState.errors
  const guard = useUnsavedGuard(formState.isDirty)

  const onSubmit = handleSubmit((values) => {
    if (receive.isPending) return // aria-disabled keeps focus on the button, so guard here
    if (!values.depositor) return // the schema refused it already
    setFailure(undefined)
    receive.mutate(receiptBody(values, values.depositor), {
      onSuccess: (deposit) => {
        guard.allowLeaving() // the move to the saved deposit is not a way out of the form
        onReceived(deposit)
      },
      onError: (error) => setFailure(applyServerErrors(error, FIELDS, setError) ? undefined : errorMessage(error)),
    })
  })

  return (
    <FormProvider {...form}>
      <Box component="form" onSubmit={onSubmit} noValidate aria-label="Receive a deposit">
        <Stack spacing={2} sx={{ maxWidth: 640 }}>
          <Typography component="h2" variant="h6">
            Depositor
          </Typography>
          <DepositorField labId={labId} error={errors.depositor?.message} value={depositor ?? null} onChange={onDepositorChange} onBlur={onDepositorBlur} name={depositorName} ref={depositorRef} />
          <Box>
            <Button
              onClick={(event) => {
                spot.current = rememberFocus(event.currentTarget)
                setAdding({ open: true })
              }}
            >
              Add a depositor
            </Button>
          </Box>

          <Typography component="h2" variant="h6">
            Receipt
          </Typography>
          <ReceiptFields register={register} errors={errors} condition={condition} />

          <Typography component="h2" variant="h6">
            Terms
          </Typography>
          <TermsFields labId={labId} />

          <FormError message={errors.root?.server?.message ?? failure} />
          <Box>
            <Button type="submit" variant="contained" aria-disabled={receive.isPending}>
              Record the deposit
            </Button>
          </Box>
        </Stack>
      </Box>
      {guard.dialog}
      {adding && (
        <DepositorDialog
          labId={labId}
          open={adding.open}
          onSaved={(saved) => onDepositorChange(saved)}
          onClose={() => setAdding((current) => current && { open: false })}
          onExited={() => {
            spot.current?.restore()
            spot.current = null
            setAdding(null)
          }}
        />
      )}
    </FormProvider>
  )
}
