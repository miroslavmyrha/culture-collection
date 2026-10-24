import type { components } from '@/api/schema'

export type Overview = components['schemas']['Overview']
export type WaitingGroup = components['schemas']['WaitingGroup']
export type WaitingItem = components['schemas']['WaitingItem']
export type MyLab = components['schemas']['MyLab']
export type ActivityLine = components['schemas']['ActivityLine']
export type Kind = WaitingGroup['kind']
export type Action = MyLab['actions'][number]
export type Role = MyLab['role']
export { actorLabel, moment } from '@/lib/activity'

/** The heading of each group on Home, in the server's order (overview/selectors.py, Kind). */
export const KIND_TITLES: Record<Kind, string> = {
  deposit_received: 'Deposits received',
  deposit_checking: 'Deposits in checking',
  batch_checks_missing: 'Batches waiting for their checks',
  batch_to_release: 'Batches to release',
  batch_on_hold: 'Batches on hold',
  request_to_decide: 'Requests to decide',
  shipment_to_confirm: 'Shipments to confirm',
  request_to_ship: 'Requests to ship',
  recipient_permit_expiring: 'Recipient permits expiring',
  lab_permit_expiring: 'Lab permits expiring',
  vials_to_destroy: 'Vials to destroy',
}

export const ACTION_LABELS: Record<Action, string> = {
  receive_deposit: 'Receive a deposit',
  record_check: 'Record a check',
  find_vial: 'Find a vial',
  enter_request: 'Enter a request',
}
export const ACTIONS = ['receive_deposit', 'record_check', 'find_vial', 'enter_request'] as const satisfies readonly Action[]

export const ROLE_LABELS: Record<Role, string> = { viewer: 'Viewer', technician: 'Technician', curator: 'Curator', manager: 'Manager' }

/** How many of each batch status, the ones there are: "1 pending check, 3 released". */
export function batchSummary(batches: MyLab['batches']): string {
  const parts = [
    [batches.pending_check, 'pending check'],
    [batches.on_hold, 'on hold'],
    [batches.released, 'released'],
    [batches.exhausted, 'exhausted'],
  ] as const
  const shown = parts.filter(([count]) => count > 0).map(([count, label]) => `${count} ${label}`)
  return shown.length ? shown.join(', ') : 'None'
}
