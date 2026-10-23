import type { Tone } from '@/components/ui'

// Which status gets a colour. The ordinary state has none: a list of 200 green "Active" labels
// says nothing, and colour should mark what needs a look. Keys are the server's status values.
export const REQUEST_TONES: Record<string, Tone> = { submitted: 'warning', approved: 'info', awaiting_confirmation: 'warning', shipped: 'success', rejected: 'danger', cancelled: 'neutral' }
export const DEPOSIT_TONES: Record<string, Tone> = { received: 'info', checking: 'warning', accepted: 'success', rejected: 'danger' }
export const STRAIN_TONES: Record<string, Tone> = { pending: 'warning', restricted: 'regulated', deaccessioned: 'neutral' }
export const BATCH_TONES: Record<string, Tone> = { released: 'success', pending_check: 'info', on_hold: 'warning', exhausted: 'neutral' }
export const VIAL_TONES: Record<string, Tone> = {
  reserved: 'info',
  consumed: 'neutral',
  distributed: 'neutral',
  quarantined: 'warning',
  to_destroy: 'warning',
  destroyed: 'neutral',
  lost: 'danger',
  entered_in_error: 'neutral',
}
export const UNIT_TONES: Record<string, Tone> = { out_of_service: 'warning', retired: 'neutral' }
