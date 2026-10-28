import { locationText, OUT_OF_A_BOX, type Vial } from '../schemas'
import { RevealLocation } from './RevealLocation'

/**
 * Where a vial lies, as every vial list shows it (ADR 0009): the place of a vial of a strain
 * without restrictions; for a regulated one "Hidden", with the reveal for a holder of the lab's
 * location grant; otherwise why it is in no box. The strain's Material tab and a request's
 * vials to pull (#143) both show it, so the masking reads the same in both.
 */
export function VialPlace({ labId, vial }: { labId: string; vial: Vial }) {
  if (vial.location) return <>{locationText(vial.location)}</>
  if (vial.location_masked) return vial.can_reveal ? <RevealLocation labId={labId} vial={vial} /> : <>Hidden: regulated strain</>
  return <>{OUT_OF_A_BOX.includes(vial.status) ? 'Left the collection' : 'Not placed'}</>
}
