import { zodResolver } from '@hookform/resolvers/zod'
import { type Ref, useEffect, useState } from 'react'
import { type Control, Controller, type FieldErrors, useFieldArray, type UseFieldArrayReturn, useForm, type UseFormRegister, type UseFormRegisterReturn, type UseFormSetError } from 'react-hook-form'
import { Alert, AutocompleteField, Box, Button, SelectField, Stack, TextField, Typography } from '@/components/ui'
import { errorMessage, isApiError } from '@/lib/api'
import { applyServerErrors } from '@/lib/forms'
import { useSubmitRequest } from '../api/mutations'
import { ALL_REQUESTERS, useRequesterList, useStrainChoices } from '../api/queries'
import { options, type Request, type RequestForm, type RequestValues, requestSchema, type StrainChoice, USE_LABELS, USES } from '../schemas'

type Props = { labId: string; onSubmitted: (request: Request) => void }

const LEVELS = [
  { value: '', label: 'Choose' },
  { value: '1', label: '1' },
  { value: '2', label: '2' },
  { value: '3', label: '3' },
  { value: '4', label: '4' },
]
const blankLine = () => ({ strain: null, quantity: '1' })

/** What is sent: the strains left empty are dropped, the end use trimmed. */
const requestBody = (values: RequestValues) => ({
  requester: values.requester,
  use: values.use,
  end_use: values.end_use.trim(),
  containment_level: Number(values.containment_level),
  lines: values.lines.flatMap((line) => (line.strain ? [{ strain: line.strain.public_id, quantity: line.quantity }] : [])),
})

/**
 * For curators: a request as the requester sent it. The requester is chosen from those the
 * lab confirmed; the destination is its country. Each line names a strain and how many vials.
 * The server pins each strain's terms and MTA version and says what stands in the way.
 */
export function NewRequestForm({ labId, onSubmitted }: Props) {
  const submit = useSubmitRequest(labId)
  const requesters = useRequesterList(labId, ALL_REQUESTERS)
  const [failure, setFailure] = useState<string>()
  const { control, register, handleSubmit, formState, setError } = useForm<RequestForm, unknown, RequestValues>({
    resolver: zodResolver(requestSchema),
    defaultValues: { requester: '', use: '', end_use: '', containment_level: '', lines: [blankLine()] },
  })
  const lines = useFieldArray({ control, name: 'lines' })
  const errors = formState.errors

  const onSubmit = handleSubmit((values) => {
    if (submit.isPending) return // aria-disabled keeps focus on the button, so guard here
    setFailure(undefined)
    submit.mutate(
      requestBody(values),
      {
        onSuccess: onSubmitted,
        onError: (error) => setFailure(requestFailure(error, [...REQUEST_FIELDS, ...lineFields(lines.fields.length)], setError)),
      },
    )
  })
  const message = errors.root?.server?.message ?? failure

  return (
    <Box component="form" onSubmit={onSubmit} noValidate aria-label="New request">
      <Stack spacing={2} sx={{ maxWidth: 640 }}>
        <RequesterSelect query={requesters} error={errors.requester?.message} registration={register('requester')} />
        <SelectField label="Use" options={[{ value: '', label: 'Choose' }, ...options(USE_LABELS, USES)]} error={errors.use?.message} {...register('use')} />
        <TextField label="End use" hint="What the recipient will do with it, in words. Name no person." multiline minRows={2} error={errors.end_use?.message} {...register('end_use')} />
        <SelectField label="Declared containment level" hint="The level of the requester's laboratory, as it declares it." options={LEVELS} error={errors.containment_level?.message} {...register('containment_level')} />

        <LinesFieldset labId={labId} control={control} register={register} errors={errors} lines={lines} />

        {message && <Alert severity="error">{message}</Alert>}
        <Box>
          <Button type="submit" variant="contained" aria-disabled={submit.isPending}>
            Enter the request
          </Button>
        </Box>
      </Stack>
    </Box>
  )
}

const REQUEST_FIELDS = ['requester', 'use', 'end_use', 'containment_level', 'lines'] as const
const lineFields = (count: number) => Array.from({ length: count }, (_, i) => [`lines.${i}.strain` as const, `lines.${i}.quantity` as const]).flat()
const OUTSIDE_EU = ['export_not_supported', 'export_of_regulated_strain']

/** An export the collection does not make lands on the requester; anything else on its field, or as a banner. */
function requestFailure(error: Error, fields: readonly Parameters<typeof applyServerErrors<RequestForm>>[1][number][], setError: UseFormSetError<RequestForm>): string | undefined {
  if (isApiError(error, 422) && OUTSIDE_EU.includes(String(error.code))) {
    setError('requester', { type: 'server', message: 'This requester is outside the EU: the collection ships only inside the EU.' }, { shouldFocus: true })
    return undefined
  }
  return applyServerErrors(error, fields, setError) ? undefined : errorMessage(error)
}

/** Mounted once the requesters are loaded: a native select keeps its value only if the option exists. */
function RequesterSelect({ query, error, registration }: { query: ReturnType<typeof useRequesterList>; error: string | undefined; registration: UseFormRegisterReturn<'requester'> }) {
  if (query.data === undefined) return <Typography>{query.isError ? 'The requesters could not be loaded. Reload the page.' : 'Loading the requesters…'}</Typography>
  const usable = query.data.results.filter((r) => !r.erased)
  if (usable.length === 0) return <Typography>No requester is recorded yet: add one on the requesters page first.</Typography>
  return (
    <SelectField
      label="Requester"
      hint="An institution with a confirmed microbiology laboratory. The destination is its country."
      options={[{ value: '', label: 'Choose' }, ...usable.map((r) => ({ value: r.public_id, label: `${r.institution} (${r.country})` }))]}
      error={error}
      {...registration}
    />
  )
}

type LineRowProps = {
  labId: string
  index: number
  control: Control<RequestForm, unknown, RequestValues>
  register: UseFormRegister<RequestForm>
  errors: FieldErrors<RequestForm>
  onRemove: (() => void) | undefined
}

function LineRow({ labId, index: i, control, register, errors, onRemove }: LineRowProps) {
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap sx={{ alignItems: { sm: 'flex-start' } }}>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Controller
          control={control}
          name={`lines.${i}.strain`}
          render={({ field }) => (
            <StrainField labId={labId} label={`Strain ${i + 1}`} value={field.value ?? null} onChange={field.onChange} onBlur={field.onBlur} name={field.name} ref={field.ref} error={errors.lines?.[i]?.strain?.message} />
          )}
        />
      </Box>
      <TextField label={`Vials of strain ${i + 1}`} inputMode="numeric" autoComplete="off" sx={{ width: { sm: 140 } }} error={errors.lines?.[i]?.quantity?.message} {...register(`lines.${i}.quantity`)} />
      {onRemove && (
        <Button onClick={onRemove} sx={{ mt: { sm: 1 } }}>
          Remove strain {i + 1}
        </Button>
      )}
    </Stack>
  )
}

type LinesFieldsetProps = Omit<LineRowProps, 'index' | 'onRemove'> & { lines: UseFieldArrayReturn<RequestForm, 'lines'> }

/** The strains asked for, one row each, at most 20. */
function LinesFieldset({ labId, control, register, errors, lines }: LinesFieldsetProps) {
  return (
    <Box component="fieldset" sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 2, m: 0, minWidth: 0 }}>
      <Typography component="legend" sx={{ px: 1 }}>
        Strains
      </Typography>
      <Stack spacing={2}>
        {lines.fields.map((line, i) => (
          <LineRow key={line.id} labId={labId} index={i} control={control} register={register} errors={errors} onRemove={lines.fields.length > 1 ? () => lines.remove(i) : undefined} />
        ))}
      </Stack>
      {errors.lines?.message && <Typography color="error">{errors.lines.message}</Typography>}
      <Box sx={{ mt: 2 }}>
        <Button variant="outlined" onClick={() => lines.append(blankLine())} aria-disabled={lines.fields.length >= 20}>
          Add a strain
        </Button>
      </Box>
    </Box>
  )
}

const WAIT_MS = 250

function useSettled(text: string): string {
  const [settled, setSettled] = useState(text)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(text), WAIT_MS)
    return () => clearTimeout(timer)
  }, [text])
  return settled
}

const strainLabel = (s: StrainChoice) => `${s.accession_number ?? 'pending'}, ${s.taxon.name}`

/** While a strain is typed for, the matches. Once one is chosen, that one alone. */
const strainOptions = (typing: boolean, found: StrainChoice[] | undefined, value: StrainChoice | null) => (typing ? (found ?? []) : value ? [value] : [])

/** The text of the box follows the chosen strain when it is changed from outside, such as by a reset. */
function useChosenText(value: StrainChoice | null) {
  const [text, setText] = useState(value ? strainLabel(value) : '')
  const [shown, setShown] = useState(value?.public_id)
  if (shown !== value?.public_id) {
    setShown(value?.public_id)
    setText(value ? strainLabel(value) : '')
  }
  return [text, setText] as const
}

type StrainFieldProps = {
  labId: string
  label: string
  error?: string | undefined
  value: StrainChoice | null
  onChange: (strain: StrainChoice | null) => void
  onBlur?: () => void
  name?: string
  ref?: Ref<HTMLInputElement>
}

/** A strain of the lab, found by its number or name. */
function StrainField({ labId, label, error, value, onChange, onBlur, name, ref }: StrainFieldProps) {
  const [text, setText] = useChosenText(value)
  const search = useSettled(text.trim())
  const typing = value === null || text !== strainLabel(value)
  const found = useStrainChoices(labId, search, typing && search.length > 0)
  return (
    <AutocompleteField<StrainChoice>
      label={label}
      hint="Type part of the number or name, then choose."
      error={error}
      name={name}
      ref={ref}
      onBlur={onBlur}
      options={strainOptions(typing, found.data?.results, value)}
      value={value}
      onChange={onChange}
      inputValue={text}
      onInputChange={setText}
      getOptionLabel={strainLabel}
      getOptionKey={(s) => s.public_id}
      isOptionEqualToValue={(a, b) => a.public_id === b.public_id}
      loading={found.isFetching}
      noOptionsText={search ? 'No strain matches' : 'Type a number or name'}
    />
  )
}
