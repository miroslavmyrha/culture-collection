import { zodResolver } from '@hookform/resolvers/zod'
import { useRef, useState } from 'react'
import { FormProvider, useController, useForm, useWatch } from 'react-hook-form'
import { useUnsavedGuard } from '@/components/UnsavedGuard'
import { Alert, Box, Button, SelectField, Stack, TextField, Typography } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { type FocusReturn, rememberFocus } from '@/lib/focus'
import { applyServerErrors } from '@/lib/forms'
import { useReceiveDeposit } from '../api/mutations'
import { CONDITION_LABELS, CONDITIONS, type Deposit, emptyTerms, options, type ReceiveForm, type ReceiveValues, receiveSchema, termsBody } from '../schemas'
import { DepositorDialog } from './DepositorDialog'
import { DepositorField } from './DepositorField'
import { TERMS_FIELDS, TermsFields } from './TermsFields'

type Props = { labId: string; onReceived: (deposit: Deposit) => void }

const FIELDS = ['depositor', 'received_on', 'condition', 'condition_note', 'name_as_received', 'depositor_passages', ...TERMS_FIELDS] as const
const today = () => new Date().toLocaleDateString('sv') // YYYY-MM-DD in local time

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
  const form = useForm<ReceiveForm, unknown, ReceiveValues>({
    resolver: zodResolver(receiveSchema),
    defaultValues: {
      depositor: null,
      received_on: today(),
      condition: 'intact',
      condition_note: '',
      name_as_received: '',
      depositor_passages: '',
      terms: emptyTerms(),
    },
  })
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
    receive.mutate(
      {
        depositor: values.depositor.public_id,
        received_on: values.received_on,
        condition: values.condition,
        condition_note: values.condition_note,
        name_as_received: values.name_as_received,
        depositor_passages: values.depositor_passages === '' ? null : Number(values.depositor_passages),
        terms: termsBody(values.terms),
      },
      {
        onSuccess: (deposit) => {
          guard.allowLeaving() // the move to the saved deposit is not a way out of the form
          onReceived(deposit)
        },
        onError: (error) => {
          if (!applyServerErrors(error, FIELDS, setError)) setFailure(errorMessage(error))
        },
      },
    )
  })
  const message = errors.root?.server?.message ?? failure

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
          <TextField label="Received on" hint="YYYY-MM-DD" autoComplete="off" error={errors.received_on?.message} {...register('received_on')} />
          <TextField label="Name as received" hint="As the depositor gave it. The strain keeps it unchanged." autoComplete="off" error={errors.name_as_received?.message} {...register('name_as_received')} />
          <SelectField label="Condition on arrival" options={options(CONDITION_LABELS, CONDITIONS)} error={errors.condition?.message} {...register('condition')} />
          <TextField
            label="Note on the condition"
            hint={condition === 'intact' ? 'Optional. About the material: name no person.' : 'Say what was wrong with it. Name no person.'}
            multiline
            minRows={2}
            error={errors.condition_note?.message}
            {...register('condition_note')}
          />
          <TextField label="Passages stated by the depositor" hint="Optional. How many times it was subcultured before it came." inputMode="numeric" autoComplete="off" error={errors.depositor_passages?.message} {...register('depositor_passages')} />

          <Typography component="h2" variant="h6">
            Terms
          </Typography>
          <TermsFields labId={labId} />

          {message && <Alert severity="error">{message}</Alert>}
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
