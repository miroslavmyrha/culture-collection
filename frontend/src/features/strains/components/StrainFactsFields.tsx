import { type ReactNode, type Ref, useMemo } from 'react'
import type { ControllerRenderProps, FieldErrors, UseFieldArrayReturn, UseFormRegister } from 'react-hook-form'
import { Box, Button, SelectField, Stack, TextField, Typography } from '@/components/ui'
import { countryOptions } from '@/lib/countries'
import {
  emptyRestriction,
  type StrainFactsForm as Values,
  GMO_CATEGORIES,
  GMO_CATEGORY_LABELS,
  options,
  PATHOGENICITY_LABELS,
  REFERENCE_HINTS,
  RESTRICTION_KINDS,
  RESTRICTION_LABELS,
  type RestrictionKind,
} from '../schemas'
import { TaxonField } from './TaxonField'

type Register = UseFormRegister<Values>
type Errors = FieldErrors<Values>

const PATHOGENICITY = options(PATHOGENICITY_LABELS, ['unknown', 'none_known', 'pathogenic'])
const RISK_GROUP_OPTIONS = [
  { value: '', label: 'Choose' },
  ...['1', '2', '3', '4'].map((value) => ({ value, label: value })),
]
const KIND_OPTIONS = options(RESTRICTION_LABELS, RESTRICTION_KINDS)
const CATEGORY_OPTIONS = [{ value: '', label: 'Choose' }, ...GMO_CATEGORIES.map((value) => ({ value: String(value), label: GMO_CATEGORY_LABELS[value] ?? '' }))]

function Heading({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <Typography component="h3" variant="h6" id={id}>
      {children}
    </Typography>
  )
}

type IdentityProps = {
  nameAsReceived: string
  /** The taxon's controller, called before every register() so the taxon is the first field in focus order. */
  taxon: ControllerRenderProps<Values, 'taxon'>
  register: Register
  errors: Errors
}

/** What the strain is: its taxon, the name as received, and how it was identified. */
export function IdentityFields({ nameAsReceived, taxon, register, errors }: IdentityProps) {
  const { value, onChange, onBlur, name, ref } = taxon
  return (
    <>
      <Heading>Identity</Heading>
      <TaxonField
        label="Taxon"
        hint="Type part of the name, then choose."
        error={errors.taxon?.message}
        value={value ?? null}
        onChange={onChange}
        onBlur={onBlur}
        name={name}
        ref={ref}
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
    </>
  )
}

/** The risk group and what it rests on, and the pathogenicity. */
export function BiosafetyFields({ register, errors }: { register: Register; errors: Errors }) {
  return (
    <>
      <Heading>Biosafety</Heading>
      <SelectField
        label="Risk group"
        hint="For humans, nařízení vlády 361/2007 Sb. The collection holds groups 1 to 3."
        options={RISK_GROUP_OPTIONS}
        error={errors.risk_group?.message}
        {...register('risk_group')}
      />
      <TextField
        label="Risk group basis"
        hint="What the group rests on: the entry of annex 7 of 361/2007 Sb., a catalogue or a publication. An agent the annex does not list is not thereby group 1. Name no person."
        multiline
        minRows={2}
        error={errors.risk_group_basis?.message}
        {...register('risk_group_basis')}
      />
      <SelectField label="Animal pathogenicity" options={PATHOGENICITY} error={errors.animal_pathogenicity?.message} {...register('animal_pathogenicity')} />
      <SelectField label="Plant pathogenicity" options={PATHOGENICITY} error={errors.plant_pathogenicity?.message} {...register('plant_pathogenicity')} />
    </>
  )
}

/** Where the strain was isolated: the source, the country and the date. */
export function OriginFields({ register, errors }: { register: Register; errors: Errors }) {
  const countries = useMemo(() => countryOptions(), [])
  return (
    <>
      <Heading>Origin</Heading>
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
    </>
  )
}

type RestrictionsProps = {
  rows: UseFieldArrayReturn<Values, 'restrictions'>
  /** The kinds as typed so far: a row's own fields follow its kind. */
  kinds: Values['restrictions'] | undefined
  addButton: Ref<HTMLButtonElement>
  /** After a row is removed: the focus goes to the button that adds rows. */
  onRemoved: () => void
  register: Register
  errors: Errors
}

/** Every regulatory list the agent is on, a fieldset for each, and the button that adds one. */
export function RestrictionFields({ rows, kinds, addButton, onRemoved, register, errors }: RestrictionsProps) {
  return (
    <>
      <Heading id="restrictions-heading">Restrictions</Heading>
      <Typography>Every regulatory list the agent is on. A strain on none needs nothing here.</Typography>
      {rows.fields.map((row, index) => (
        <RestrictionRow
          key={row.id}
          index={index}
          kind={kinds?.[index]?.kind ?? row.kind}
          register={register}
          errors={errors.restrictions?.[index]}
          onRemove={() => {
            rows.remove(index)
            onRemoved()
          }}
        />
      ))}
      {errors.restrictions?.message && <Typography color="error">{errors.restrictions.message}</Typography>}
      <Box>
        {/* aria-disabled and a guard: at ten rows a disabled button would drop the focus. */}
        <Button ref={addButton} aria-disabled={rows.fields.length >= 10} onClick={() => {
            if (rows.fields.length < 10) rows.append({ ...emptyRestriction })
          }}
        >
          Add a restriction
        </Button>
      </Box>
    </>
  )
}

type RowProps = {
  index: number
  kind: RestrictionKind
  register: Register
  errors: NonNullable<Errors['restrictions']>[number]
  onRemove: () => void
}

/** The field only some kinds have: the act a dual-use entry was read in, the category of a GMO. */
function KindExtras({ index, kind, register, errors }: Omit<RowProps, 'onRemove'>) {
  if (kind === 'dual_use')
    return (
      <TextField
        label="Act Annex I was read in"
        hint="The delegated act that replaced Annex I, for example (EU) 2025/2003"
        autoComplete="off"
        error={errors?.act?.message}
        {...register(`restrictions.${index}.act`)}
      />
    )
  if (kind === 'gmo')
    return (
      <SelectField
        label="Contained use category"
        hint="Act 78/2004 Sb., § 15"
        options={CATEGORY_OPTIONS}
        error={errors?.gmo_category?.message}
        {...register(`restrictions.${index}.gmo_category`)}
      />
    )
  return null
}

function RestrictionRow({ index, kind, register, errors: rowErrors, onRemove }: RowProps) {
  const number = index + 1
  return (
    <Box component="fieldset" sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 2, m: 0, minWidth: 0 }}>
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
        <KindExtras index={index} kind={kind} register={register} errors={rowErrors} />
        <Box>
          <Button onClick={onRemove}>Remove restriction {number}</Button>
        </Box>
      </Stack>
    </Box>
  )
}
