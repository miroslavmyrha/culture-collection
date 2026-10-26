import { DepositorField } from './DepositorField'
import { useDepositor } from '../api/queries'

type Props = {
  labId: string
  /** The public id of the depositor the list is filtered by, from the URL. */
  value: string | undefined
  onChange: (depositor: string | undefined) => void
}

/**
 * The depositor filter of the strain list: the field of the receipt form, with the depositor
 * of the URL loaded by id so a reload shows who the list is filtered by.
 */
export function DepositorFilterField({ labId, value, onChange }: Props) {
  const depositor = useDepositor(labId, value)
  return (
    <DepositorField
      labId={labId}
      hint="Strains accepted from this depositor's deposits"
      // The list is filtered by a depositor the field cannot show: an empty field would hide that.
      error={value && depositor.isError ? 'Could not load the depositor this list is filtered by.' : undefined}
      value={value && depositor.data ? depositor.data : null}
      onChange={(picked) => onChange(picked?.public_id)}
    />
  )
}
